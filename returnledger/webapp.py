"""Read-only web UI over an exported dataset (standard library only).

    python -m returnledger serve --scale starter      # http://localhost:8000

The server loads the dataset's CSVs once, builds indexes and serves a single-page app from
returnledger/web/ plus a small JSON API. Ground truth is only shown on the RMA detail page,
clearly marked as evaluation data; the audit findings come from audit.py output.
"""
import csv
import json
import mimetypes
import os
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote

from . import storage
from .schema import TABLE_BY_NAME

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


def _row(table, row):
    return {f.name: storage.to_json(row[f.name], f.type) for f in TABLE_BY_NAME[table].fields}


def _read_json(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


class App:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        t = self.t = storage.load_tables(data_dir)
        reports = os.path.join(data_dir, "reports")
        self.manifest = _read_json(os.path.join(data_dir, "manifest.json"))
        self.metrics = _read_json(os.path.join(reports, "metrics.json"))
        self.validation = _read_json(os.path.join(reports, "validation_summary.json"))
        self.evaluation = _read_json(os.path.join(reports, "evaluation.json"))
        self.reproducibility = _read_json(os.path.join(reports, "reproducibility.json"))
        self.robustness = _read_json(os.path.join(reports, "robustness.json"))
        path = os.path.join(reports, "audit_findings.csv")
        self.findings = []
        if os.path.exists(path):
            with open(path, newline="", encoding="utf-8") as fh:
                self.findings = list(csv.DictReader(fh))
        self.gt, _ = storage.load_ground_truth(data_dir)

        def group(table, key):
            out = defaultdict(list)
            for r in t[table]:
                out[r[key]].append(r)
            return out

        self.orders = {o["order_id"]: o for o in t["orders"]}
        self.customers = {c["customer_id"]: c for c in t["customer"]}
        self.products = {p["sku"]: p for p in t["product"]}
        self.order_lines = {x["order_line_id"]: x for x in t["order_line"]}
        self.rmas = {r["rma_id"]: r for r in t["return_request"]}
        self.lines_by_rma = group("return_line", "rma_id")
        self.auth_by_rma = {a["rma_id"]: a for a in t["return_authorization"]}
        self.auth_line = {a["return_line_id"]: a for a in t["authorization_line"]}
        self.ships_by_rma = group("return_shipment", "rma_id")
        self.ship_lines = group("shipment_line", "shipment_id")
        self.ins_by_line = group("inspection", "return_line_id")
        self.disp_by_ins = {d["inspection_id"]: d for d in t["inventory_disposition"]}
        self.mov_by_disp = {m["disposition_id"]: m for m in t["inventory_movement"]}
        self.refunds_by_rma = group("refund", "rma_id")
        self.refund_lines = group("refund_line", "refund_id")
        self.exchange_by_rma = {o["source_rma_id"]: o for o in t["orders"] if o["order_type"] == "EXCHANGE"}
        self.events = group("status_event", "entity_id")
        self.findings_by_rma = defaultdict(list)
        for f in self.findings:
            self.findings_by_rma[f["rma_id"]].append(f)
        self.gt_by_rma = defaultdict(list)
        for a in self.gt:
            self.gt_by_rma[a["rma_id"]].append(a)
        self._rma_list = self._build_rma_list()

    # --------------------------------------------------------------- endpoints
    def summary(self):
        reached = defaultdict(set)
        for e in self.t["status_event"]:
            if e["entity_type"] == "RETURN_REQUEST":
                reached[e["to_status"]].add(e["entity_id"])
        n = len(self.rmas)
        approved = sum(1 for a in self.t["return_authorization"] if a["approved_qty_total"] > 0)
        funnel = [
            {"stage": "Requested", "count": n, "help": "Customer submitted a return request (RMA)"},
            {"stage": "Decided", "count": len(self.auth_by_rma), "help": "Eligibility rules applied to every line"},
            {"stage": "Authorized", "count": approved, "help": "At least one line approved; return label issued"},
            {"stage": "Shipped", "count": len(reached["IN_TRANSIT"]), "help": "Parcel scanned by the carrier"},
            {"stage": "Received", "count": len(reached["RECEIVED"]), "help": "All parcels arrived at the warehouse"},
            {"stage": "Inspected", "count": len(reached["INSPECTED"]), "help": "Condition graded for every unit"},
            {"stage": "Resolved", "count": len(reached["REFUNDED"]) + len(reached["EXCHANGED"]) + len(reached["CLOSED_NO_REFUND"]),
             "help": "Refunded, exchanged or closed with nothing refundable"},
        ]
        exits = {"Rejected": len(reached["REJECTED"]), "Label expired (never shipped)": len(reached["EXPIRED"]),
                 "Lost in transit": len(reached["LOST_IN_TRANSIT"]),
                 "Pending decision": n - len(self.auth_by_rma)}
        resolved = {"Refunded": len(reached["REFUNDED"]), "Exchanged": len(reached["EXCHANGED"]),
                    "Closed, nothing refundable": len(reached["CLOSED_NO_REFUND"])}
        return {"manifest": self.manifest, "metrics": self.metrics, "funnel": funnel, "exits": exits,
                "resolved": resolved, "evaluation": self.evaluation,
                "validation_status": self.validation and self.validation["overall_status"],
                "validation_totals": self.validation and self.validation["totals"]}

    def rma_list(self):
        return self._rma_list

    def _build_rma_list(self):
        out = []
        for rid, r in self.rmas.items():
            lines = self.lines_by_rma[rid]
            cats = sorted({self.order_lines[l["order_line_id"]]["category"] for l in lines})
            paid = sum(x["paid_amount"] for x in self.refunds_by_rma.get(rid, []))
            out.append({
                "rma_id": rid, "requested_at": r["requested_at"].isoformat(timespec="minutes"),
                "status": r["current_status"], "resolution": r["resolution_type"], "channel": r["return_channel"],
                "order_id": r["order_id"], "tier": self.customers[r["customer_id"]]["loyalty_tier"],
                "lines": len(lines), "categories": cats,
                "decision": self.auth_by_rma[rid]["decision_status"] if rid in self.auth_by_rma else "PENDING",
                "paid": round(paid / 100, 2),
                "issues": sorted({f["issue_type"] for f in self.findings_by_rma.get(rid, [])}),
                "late": any(self.auth_line.get(l["return_line_id"], {}).get("days_since_delivery", 0)
                            > self.auth_line.get(l["return_line_id"], {}).get("effective_window_days", 10 ** 6)
                            for l in lines),
            })
        out.sort(key=lambda x: x["rma_id"])
        return out

    def rma(self, rid):
        r = self.rmas.get(rid)
        if r is None:
            return None
        order = self.orders[r["order_id"]]
        lines = []
        for rl in self.lines_by_rma[rid]:
            ol = self.order_lines[rl["order_line_id"]]
            insp = []
            for i in self.ins_by_line.get(rl["return_line_id"], []):
                d = self.disp_by_ins.get(i["inspection_id"])
                insp.append({**_row("inspection", i),
                             "disposition": _row("inventory_disposition", d) if d else None,
                             "movement": _row("inventory_movement", self.mov_by_disp[d["disposition_id"]]) if d else None})
            al = self.auth_line.get(rl["return_line_id"])
            lines.append({**_row("return_line", rl), "order_line": _row("order_line", ol),
                          "product_name": self.products[ol["sku"]]["product_name"],
                          "decision": _row("authorization_line", al) if al else None, "inspections": insp})
        shipments = [{**_row("return_shipment", s), "lines": [_row("shipment_line", x) for x in self.ship_lines[s["shipment_id"]]]}
                     for s in self.ships_by_rma.get(rid, [])]
        refunds = [{**_row("refund", x), "lines": [_row("refund_line", y) for y in self.refund_lines[x["refund_id"]]]}
                   for x in self.refunds_by_rma.get(rid, [])]
        exch = self.exchange_by_rma.get(rid)
        related = [order["order_id"], rid] + [s["shipment_id"] for s in self.ships_by_rma.get(rid, [])] + \
                  [x["refund_id"] for x in self.refunds_by_rma.get(rid, [])] + ([exch["order_id"]] if exch else [])
        events = sorted((e for k in related for e in self.events.get(k, [])), key=lambda e: e["event_id"])
        auth = self.auth_by_rma.get(rid)
        return {
            "rma": _row("return_request", r), "order": _row("orders", order),
            "customer": _row("customer", self.customers[r["customer_id"]]),
            "authorization": _row("return_authorization", auth) if auth else None,
            "lines": lines, "shipments": shipments, "refunds": refunds,
            "exchange_order": _row("orders", exch) if exch else None,
            "events": [_row("status_event", e) for e in events],
            "findings": self.findings_by_rma.get(rid, []), "ground_truth": self.gt_by_rma.get(rid, []),
        }

    def exceptions(self):
        return {"findings": self.findings, "evaluation": self.evaluation}

    def rules(self):
        return {"policies": [_row("return_policy", p) for p in self.t["return_policy"]]}

    def quality(self):
        return {"validation": self.validation, "reproducibility": self.reproducibility,
                "robustness": self.robustness, "manifest": self.manifest}


def make_handler(app):
    routes = {"/api/summary": app.summary, "/api/rmas": app.rma_list, "/api/exceptions": app.exceptions,
              "/api/rules": app.rules, "/api/quality": app.quality}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, status, body, ctype):
            data = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _json(self, obj, status=200):
            self._send(status, json.dumps(obj, default=str), "application/json; charset=utf-8")

        def do_GET(self):
            path = unquote(urlparse(self.path).path)
            if path in routes:
                return self._json(routes[path]())
            if path.startswith("/api/rma/"):
                result = app.rma(path[len("/api/rma/"):])
                return self._json(result) if result else self._json({"error": "not found"}, 404)
            if path.startswith("/api/"):
                return self._json({"error": "unknown endpoint"}, 404)
            name = "index.html" if path in ("/", "") else path.lstrip("/")
            full = os.path.normpath(os.path.join(WEB_DIR, name))
            if not full.startswith(WEB_DIR + os.sep) or not os.path.isfile(full):
                return self._send(404, "not found", "text/plain")
            with open(full, "rb") as fh:
                ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
                if ctype.startswith("text/") or ctype.endswith("javascript"):
                    ctype += "; charset=utf-8"
                self._send(200, fh.read(), ctype)

    return Handler


def serve(data_dir, port=8000, open_browser=True):
    print(f"[serve] loading {data_dir} ...")
    app = App(data_dir)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
    url = f"http://127.0.0.1:{port}/"  # not "localhost": Windows may try IPv6 first and the server is IPv4
    print(f"[serve] ReturnLedger UI running at {url}  (Ctrl+C to stop)")
    if open_browser:
        import webbrowser
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
