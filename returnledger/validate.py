"""Validation suite for an exported dataset.

Each check lists violating ids. A violation is *labelled* if its id appears in ground truth
(entity_id or related_ids) - i.e. it is a deliberately injected anomaly. A check FAILS only
if it has unlabelled violations, so the dataset is proven clean apart from documented cases.
"""
import os
import re
import sqlite3
from collections import Counter, defaultdict

from . import config as C
from . import policy as P
from .audit import run_audit
from .money import apply_rate
from .schema import TABLES, ENUMS, LIFECYCLES


class Validator:
    def __init__(self, tables, gt_anomalies, data_dir=None, expected_volume=None):
        self.t = tables
        self.data_dir = data_dir
        self.expected_volume = expected_volume or {}
        self.labelled = set()
        for a in gt_anomalies:
            self.labelled.add(a["entity_id"])
            self.labelled.update(x for x in a["related_ids"].split(";") if x)
        self.gt = gt_anomalies
        self.results = []

    def check(self, category, name, checked, violations, rule=""):
        labelled = [v for v in violations if v[0] in self.labelled]
        unlabelled = [v for v in violations if v[0] not in self.labelled]
        status = "FAIL" if unlabelled else ("PASS_WITH_LABELLED_EXCEPTIONS" if labelled else "PASS")
        self.results.append({
            "category": category, "check": name, "rule": rule, "rows_checked": checked,
            "violations": len(violations), "labelled": len(labelled), "unlabelled": len(unlabelled),
            "status": status, "examples": [f"{i}: {d}" for i, d in (unlabelled or labelled)[:3]],
        })

    # ------------------------------------------------------------------- runner
    def run(self):
        t = self.t
        self.idx = {
            "orders": {o["order_id"]: o for o in t["orders"]},
            "order_line": {o["order_line_id"]: o for o in t["order_line"]},
            "product": {p["sku"]: p for p in t["product"]},
            "rma": {r["rma_id"]: r for r in t["return_request"]},
            "rl": {r["return_line_id"]: r for r in t["return_line"]},
            "auth": {a["authorization_id"]: a for a in t["return_authorization"]},
            "auth_by_rma": {a["rma_id"]: a for a in t["return_authorization"]},
            "al": {a["return_line_id"]: a for a in t["authorization_line"]},
            "ship": {s["shipment_id"]: s for s in t["return_shipment"]},
            "ins": {i["inspection_id"]: i for i in t["inspection"]},
            "refund": {r["refund_id"]: r for r in t["refund"]},
            "disp": {d["disposition_id"]: d for d in t["inventory_disposition"]},
        }
        self.structural()
        self.referential()
        self.volume()
        self.dates()
        self.arithmetic()
        self.quantities()
        self.lifecycle()
        self.duplicates()
        self.business_rules()
        return self.summary()

    # --------------------------------------------------------------- structural
    def structural(self):
        pk_v, req_v, enum_v, pat_v, uniq_v = [], [], [], [], []
        rows = 0
        for tab in TABLES:
            data = self.t[tab.name]
            rows += len(data)
            keys = Counter(tuple(r[c] for c in tab.pk) for r in data)
            pk_v += [(":".join(map(str, k)), f"{tab.name} pk x{n}") for k, n in keys.items() if n > 1]
            for f in tab.fields:
                vals = [r[f.name] for r in data]
                ident = [r[tab.pk[0]] for r in data]
                if f.required:
                    req_v += [(i, f"{tab.name}.{f.name} is null") for i, v in zip(ident, vals) if v is None]
                if f.enum:
                    allowed = set(ENUMS[f.enum])
                    enum_v += [(i, f"{tab.name}.{f.name}={v}") for i, v in zip(ident, vals)
                               if v is not None and v not in allowed]
                if f.pattern:
                    rx = re.compile(f.pattern + r"\Z")
                    pat_v += [(i, f"{tab.name}.{f.name}={v}") for i, v in zip(ident, vals)
                              if v is not None and not rx.match(str(v))]
                if f.unique:
                    cnt = Counter(v for v in vals if v is not None)
                    uniq_v += [(str(v), f"{tab.name}.{f.name} x{n}") for v, n in cnt.items() if n > 1]
        self.check("structure", "Primary keys unique", rows, pk_v, "every table PK unique")
        self.check("structure", "Required fields present", rows, req_v, "NOT NULL per data dictionary")
        self.check("structure", "Enum values allowed", rows, enum_v, "values in allowed lists")
        self.check("structure", "ID / format patterns", rows, pat_v, "ORD-2026-000001, RMA-, RMAL-<rma>-01, RTS-, REF-...")
        self.check("structure", "Unique columns", rows, uniq_v, "email, tracking_number, rma_id on authorization ...")

    # -------------------------------------------------------------- referential
    def referential(self):
        t, idx = self.t, self.idx
        v, n = [], 0
        parents = {}
        for tab in TABLES:
            for f in tab.fields:
                if not f.fk:
                    continue
                ptab, pcol = f.fk.split(".")
                key = (ptab, pcol)
                if key not in parents:
                    parents[key] = {r[pcol] for r in t[ptab]}
                for r in t[tab.name]:
                    n += 1
                    if r[f.name] is not None and r[f.name] not in parents[key]:
                        v.append((r[tab.pk[0]], f"{tab.name}.{f.name}={r[f.name]} missing in {ptab}"))
        sl = {(s["shipment_id"], s["return_line_id"]) for s in t["shipment_line"]}
        for i in t["inspection"]:
            n += 1
            if (i["shipment_id"], i["return_line_id"]) not in sl:
                v.append((i["inspection_id"], "inspection not on shipment_line"))
        entity_sets = {"ORDER": idx["orders"], "RETURN_REQUEST": idx["rma"], "RETURN_SHIPMENT": idx["ship"],
                       "REFUND": idx["refund"]}
        for e in t["status_event"]:
            n += 1
            if e["entity_id"] not in entity_sets[e["entity_type"]]:
                v.append((e["event_id"], f"{e['entity_type']} {e['entity_id']} missing"))
        self.check("integrity", "Foreign keys resolve (incl. composite + polymorphic)", n, v)

        if self.data_dir and os.path.exists(os.path.join(self.data_dir, "returnledger.db")):
            con = sqlite3.connect(os.path.join(self.data_dir, "returnledger.db"))
            bad = con.execute("PRAGMA foreign_key_check").fetchall()
            con.close()
            self.check("integrity", "SQLite PRAGMA foreign_key_check", len(t["status_event"]),
                       [(str(b[1]), f"{b[0]} -> {b[2]}") for b in bad], "database-enforced FKs")

        jv, n = [], 0
        for r in t["return_request"]:
            n += 1
            if idx["orders"][r["order_id"]]["customer_id"] != r["customer_id"]:
                jv.append((r["rma_id"], "customer differs from order customer"))
            if idx["orders"][r["order_id"]]["order_type"] != "SALE":
                jv.append((r["rma_id"], "return against exchange order"))
        for rl in t["return_line"]:
            n += 1
            ol = idx["order_line"][rl["order_line_id"]]
            if ol["order_id"] != idx["rma"][rl["rma_id"]]["order_id"]:
                jv.append((rl["return_line_id"], "order line belongs to a different order"))
            if ol["sku"] != rl["sku"]:
                jv.append((rl["return_line_id"], "sku differs from order line"))
        for ol in t["order_line"]:
            n += 1
            if idx["product"][ol["sku"]]["category"] != ol["category"]:
                jv.append((ol["order_line_id"], "category differs from product"))
        for al in t["authorization_line"]:
            n += 1
            if idx["auth"][al["authorization_id"]]["rma_id"] != idx["rl"][al["return_line_id"]]["rma_id"]:
                jv.append((al["authorization_line_id"], "authorization and return line on different RMAs"))
        lines_by_rma = defaultdict(list)
        for rl in t["return_line"]:
            lines_by_rma[rl["rma_id"]].append(rl)
        for a in t["return_authorization"]:
            n += 1
            missing = [rl["return_line_id"] for rl in lines_by_rma[a["rma_id"]] if rl["return_line_id"] not in idx["al"]]
            if missing:
                jv.append((a["authorization_id"], f"lines without decision {missing}"))
        for s in t["return_shipment"]:
            n += 1
            if idx["auth"][s["authorization_id"]]["rma_id"] != s["rma_id"]:
                jv.append((s["shipment_id"], "authorization belongs to other RMA"))
        for s in t["shipment_line"]:
            n += 1
            if idx["rl"][s["return_line_id"]]["rma_id"] != idx["ship"][s["shipment_id"]]["rma_id"]:
                jv.append((s["shipment_id"], "shipment line from other RMA"))
        for rf in t["refund_line"]:
            n += 1
            rl = idx["rl"][rf["return_line_id"]]
            if rl["order_line_id"] != rf["order_line_id"] or idx["ins"][rf["inspection_id"]]["return_line_id"] != rl["return_line_id"] \
                    or idx["refund"][rf["refund_id"]]["rma_id"] != rl["rma_id"]:
                jv.append((rf["refund_line_id"], "refund line joins disagree"))
        for d in t["inventory_disposition"]:
            n += 1
            ins = idx["ins"][d["inspection_id"]]
            if ins["return_line_id"] != d["return_line_id"] or idx["rl"][d["return_line_id"]]["sku"] != d["sku"]:
                jv.append((d["disposition_id"], "disposition joins disagree"))
        for m in t["inventory_movement"]:
            n += 1
            if idx["disp"][m["disposition_id"]]["sku"] != m["sku"]:
                jv.append((m["movement_id"], "movement sku differs from disposition"))
        for o in t["orders"]:
            n += 1
            if (o["order_type"] == "EXCHANGE") != (o["source_rma_id"] is not None):
                jv.append((o["order_id"], "source_rma_id must be set iff EXCHANGE"))
        self.check("integrity", "Cross-entity joins consistent", n, jv,
                   "customer/order/line/sku/RMA agree along every join path")

    # ----------------------------------------------------------------- volume
    def volume(self):
        t = self.t
        actual = {"orders": sum(1 for o in t["orders"] if o["order_type"] == "SALE"),
                  "return_requests": len(t["return_request"]), "return_lines": len(t["return_line"])}
        v = [(k, f"expected {self.expected_volume[k]} got {actual[k]}") for k in self.expected_volume
             if actual[k] != self.expected_volume[k]]
        self.check("volume", "Target volumes met exactly", 3, v, str(self.expected_volume))

    # ------------------------------------------------------------------ dates
    def dates(self):
        t, idx = self.t, self.idx
        v, n = [], 0

        def need(cond, ident, msg):
            nonlocal n
            n += 1
            if not cond:
                v.append((ident, msg))

        first_order = {}
        for o in t["orders"]:
            first_order[o["customer_id"]] = min(first_order.get(o["customer_id"], o["placed_at"]), o["placed_at"])
            need(o["shipped_at"] is None or o["placed_at"] <= o["shipped_at"], o["order_id"], "shipped before placed")
            need(o["delivered_at"] is None or o["shipped_at"] <= o["delivered_at"], o["order_id"], "delivered before shipped")
        for c in t["customer"]:
            if c["customer_id"] in first_order:
                need(c["signup_date"] <= first_order[c["customer_id"]].date(), c["customer_id"], "order before signup")
        for r in t["return_request"]:
            need(r["requested_at"] >= idx["orders"][r["order_id"]]["delivered_at"], r["rma_id"], "requested before delivery")
        for a in t["return_authorization"]:
            need(a["decided_at"] >= idx["rma"][a["rma_id"]]["requested_at"], a["authorization_id"], "decided before request")
        for s in t["return_shipment"]:
            a = idx["auth"][s["authorization_id"]]
            need(s["label_created_at"] >= a["decided_at"], s["shipment_id"], "label before authorization")
            if s["shipped_at"]:
                need(s["label_created_at"] <= s["shipped_at"] <= a["label_expires_at"], s["shipment_id"],
                     "shipped outside label validity")
            if s["received_at"]:
                need(s["shipped_at"] is not None and s["received_at"] >= s["shipped_at"], s["shipment_id"],
                     "received before shipped")
        for i in t["inspection"]:
            rec = idx["ship"][i["shipment_id"]]["received_at"]
            need(rec is not None and i["inspected_at"] >= rec, i["inspection_id"], "inspected before received")
        last_ins = defaultdict(lambda: None)
        for rf in t["refund_line"]:
            ts = idx["ins"][rf["inspection_id"]]["inspected_at"]
            if last_ins[rf["refund_id"]] is None or ts > last_ins[rf["refund_id"]]:
                last_ins[rf["refund_id"]] = ts
        for r in t["refund"]:
            need(last_ins[r["refund_id"]] is not None and r["requested_at"] >= last_ins[r["refund_id"]],
                 r["refund_id"], "refund requested before inspection")
            need(r["processed_at"] is None or r["processed_at"] >= r["requested_at"], r["refund_id"],
                 "processed before requested")
        for d in t["inventory_disposition"]:
            need(d["decided_at"] >= idx["ins"][d["inspection_id"]]["inspected_at"], d["disposition_id"],
                 "disposition before inspection")
        for m in t["inventory_movement"]:
            d = idx["disp"][m["disposition_id"]]
            need(m["moved_at"] == d["decided_at"], m["movement_id"], "movement time differs from disposition")
            need(m["moved_at"] >= idx["ins"][d["inspection_id"]]["inspected_at"], m["movement_id"],
                 "stock moved before inspection")
        for e in t["status_event"]:
            need(e["event_ts"] <= C.AS_OF, e["event_id"], "event after as-of date")
        by_cat = defaultdict(list)
        for p in t["return_policy"]:
            need(p["effective_to"] is None or p["effective_to"] >= p["effective_from"], p["policy_id"], "bad policy dates")
            by_cat[p["category"]].append(p)
        for cat, ps in by_cat.items():
            ps.sort(key=lambda p: p["effective_from"])
            for a, b in zip(ps, ps[1:]):
                need(a["effective_to"] is not None and a["effective_to"] < b["effective_from"], b["policy_id"],
                     "overlapping policy versions")
        self.check("dates", "Date ordering across the lifecycle", n, v,
                   "placed<=shipped<=delivered<=requested<=decided<=label<=shipped<=received<=inspected<=refund/disposition")

    # -------------------------------------------------------------- arithmetic
    def arithmetic(self):
        t, idx = self.t, self.idx
        v, n = [], 0
        lines_by_order = defaultdict(list)
        for ol in t["order_line"]:
            n += 1
            o = idx["orders"][ol["order_id"]]
            lines_by_order[ol["order_id"]].append(ol)
            gross = ol["qty"] * ol["unit_price"]
            if ol["net_amount"] != gross - ol["line_discount"] - ol["allocated_order_discount"] or ol["net_amount"] < 0:
                v.append((ol["order_line_id"], "net_amount mismatch"))
            exp_tax = 0 if ol["category"] in C.TAX_EXEMPT_CATEGORIES else apply_rate(ol["net_amount"], o["tax_rate"])
            if ol["tax_amount"] != exp_tax:
                v.append((ol["order_line_id"], f"tax {ol['tax_amount']} expected {exp_tax}"))
            if ol["line_total"] != ol["net_amount"] + ol["tax_amount"]:
                v.append((ol["order_line_id"], "line_total mismatch"))
        for o in t["orders"]:
            n += 1
            ls = lines_by_order[o["order_id"]]
            merch = sum(l["net_amount"] for l in ls)
            checks = {
                "items_subtotal": sum(l["qty"] * l["unit_price"] for l in ls),
                "line_discount_total": sum(l["line_discount"] for l in ls),
                "order_discount": sum(l["allocated_order_discount"] for l in ls),
                "tax_total": sum(l["tax_amount"] for l in ls),
                "order_total": merch + sum(l["tax_amount"] for l in ls) + o["shipping_fee"],
            }
            for k, exp in checks.items():
                if o[k] != exp:
                    v.append((o["order_id"], f"{k} {o[k]} expected {exp}"))
            if o["order_type"] == "SALE":
                free = o["order_channel"] == "STORE" or all(l["category"] == "GIFT_CARD" for l in ls) \
                    or merch >= C.FREE_SHIPPING_THRESHOLD_CENTS
                if o["shipping_fee"] != (0 if free else C.STANDARD_SHIPPING_CENTS):
                    v.append((o["order_id"], "shipping fee rule"))
        als_by_auth = defaultdict(list)
        for al in t["authorization_line"]:
            als_by_auth[al["authorization_id"]].append(al)
        for a in t["return_authorization"]:
            n += 1
            als = als_by_auth[a["authorization_id"]]
            if a["approved_qty_total"] != sum(x["approved_qty"] for x in als):
                v.append((a["authorization_id"], "approved_qty_total mismatch"))
            if a["decision_status"] != P.authorization_status([x["line_decision"] for x in als]):
                v.append((a["authorization_id"], "decision_status not derived from lines"))
        rls_by_refund = defaultdict(list)
        for rf in t["refund_line"]:
            n += 1
            rls_by_refund[rf["refund_id"]].append(rf)
            exp = (rf["merchandise_amount"] + rf["tax_amount"] - rf["restocking_fee"] - rf["damage_deduction"]
                   - rf["cap_adjustment"])
            if rf["line_refund_amount"] != exp or rf["line_refund_amount"] < 0:
                v.append((rf["refund_id"], f"{rf['refund_line_id']} components do not sum"))
        for r in t["refund"]:
            n += 1
            if r["lines_amount"] != sum(x["line_refund_amount"] for x in rls_by_refund[r["refund_id"]]):
                v.append((r["refund_id"], "lines_amount mismatch"))
            if r["refund_amount"] != r["lines_amount"] + r["shipping_refund"] - r["return_label_fee"]:
                v.append((r["refund_id"], "refund_amount formula"))
            if r["paid_amount"] != (r["refund_amount"] if r["current_status"] == "PAID" else 0):
                v.append((r["refund_id"], "paid_amount vs status"))
        for m in t["inventory_movement"]:
            n += 1
            if m["movement_value"] != m["qty"] * m["unit_cost"] or m["unit_cost"] != idx["product"][m["sku"]]["unit_cost"]:
                v.append((m["movement_id"], "movement value"))
        self.check("arithmetic", "Totals, tax, discounts and refund formulas reconcile", n, v,
                   "derived values recomputed from source rows")

        # Refunds never exceed what was paid (cumulative per order line and per order).
        cv, n = [], 0
        paid_line, paid_order = defaultdict(int), defaultdict(int)
        for r in sorted(t["refund"], key=lambda r: (r["processed_at"] or r["requested_at"], r["refund_id"])):
            if r["current_status"] != "PAID":
                continue
            n += 1
            over = False
            for rf in rls_by_refund[r["refund_id"]]:
                paid_line[rf["order_line_id"]] += rf["line_refund_amount"]
                over |= paid_line[rf["order_line_id"]] > idx["order_line"][rf["order_line_id"]]["line_total"]
            oid = idx["rma"][r["rma_id"]]["order_id"]
            paid_order[oid] += r["paid_amount"]
            over |= paid_order[oid] > idx["orders"][oid]["order_total"]
            if over:
                cv.append((r["refund_id"], "cumulative refund exceeds amount paid"))
        self.check("arithmetic", "Refunds <= amount paid (line and order)", n, cv, "sum(refunds) <= net + tax")

    # -------------------------------------------------------------- quantities
    def quantities(self):
        t, idx = self.t, self.idx
        v, n = [], 0
        approved_so_far = defaultdict(int)
        for al in sorted(t["authorization_line"], key=lambda a: (idx["auth"][a["authorization_id"]]["decided_at"],
                                                                  a["authorization_line_id"])):
            n += 1
            rl = idx["rl"][al["return_line_id"]]
            ol = idx["order_line"][rl["order_line_id"]]
            if al["approved_qty"] > rl["requested_qty"]:
                v.append((al["authorization_line_id"], "approved > requested"))
            approved_so_far[ol["order_line_id"]] += al["approved_qty"]
            if approved_so_far[ol["order_line_id"]] > ol["qty"]:
                v.append((al["authorization_line_id"], f"approved {approved_so_far[ol['order_line_id']]} > purchased {ol['qty']}"))
            if (al["approved_qty"] > 0) != (al["line_decision"] != "REJECTED"):
                v.append((al["authorization_line_id"], "decision vs approved qty"))
        shipped = defaultdict(int)
        for s in t["shipment_line"]:
            n += 1
            shipped[s["return_line_id"]] += s["shipped_qty"]
        for rl_id, q in shipped.items():
            al = idx["al"].get(rl_id)
            if al is None or q > al["approved_qty"]:
                v.append((rl_id, "shipped more than approved"))
        sl_qty = {(s["shipment_id"], s["return_line_id"]): s["shipped_qty"] for s in t["shipment_line"]}
        disp_by_ins = {d["inspection_id"]: d for d in t["inventory_disposition"]}
        for i in t["inspection"]:
            n += 1
            if not 0 <= i["received_qty"] <= sl_qty[(i["shipment_id"], i["return_line_id"])]:
                v.append((i["inspection_id"], "received qty outside 0..shipped"))
            d = disp_by_ins.get(i["inspection_id"])
            if d and d["qty"] != i["received_qty"]:
                v.append((d["disposition_id"], "disposed qty != received"))
        mov = {m["disposition_id"]: m for m in t["inventory_movement"]}
        for d in t["inventory_disposition"]:
            n += 1
            m = mov.get(d["disposition_id"])
            if m is None or m["to_location"] != P.DISPOSITION_LOCATION[d["disposition"]] or m["qty"] != d["qty"] \
                    or m["from_location"] != "RETURNS_DOCK":
                v.append((d["disposition_id"], "movement does not follow disposition"))
        self.check("quantity", "Quantities flow purchased >= approved >= shipped >= received = disposed", n, v,
                   "disposition controls inventory movement")

    # -------------------------------------------------------------- lifecycle
    def lifecycle(self):
        t, idx = self.t, self.idx
        v, n = [], 0
        hist = defaultdict(list)
        for e in t["status_event"]:
            hist[(e["entity_type"], e["entity_id"])].append(e)
        for (etype, eid), evs in hist.items():
            evs.sort(key=lambda e: e["event_id"])
            prev, prev_ts = None, None
            for e in evs:
                n += 1
                if e["from_status"] != prev or e["to_status"] not in LIFECYCLES[etype].get(prev, set()):
                    v.append((eid, f"illegal transition {prev}->{e['to_status']}"))
                if prev_ts and e["event_ts"] < prev_ts:
                    v.append((eid, "event time went backwards"))
                prev, prev_ts = e["to_status"], e["event_ts"]
        for table, etype, pk in [("orders", "ORDER", "order_id"), ("return_request", "RETURN_REQUEST", "rma_id"),
                                 ("return_shipment", "RETURN_SHIPMENT", "shipment_id"), ("refund", "REFUND", "refund_id")]:
            for r in t[table]:
                n += 1
                evs = hist.get((etype, r[pk]))
                if not evs or evs[-1]["to_status"] != r["current_status"]:
                    v.append((r[pk], "current_status differs from last event"))
        paid_rmas = {r["rma_id"] for r in t["refund"] if r["current_status"] == "PAID"}
        exch_rmas = {o["source_rma_id"] for o in t["orders"] if o["order_type"] == "EXCHANGE"}
        expired_rmas = {s["rma_id"] for s in t["return_shipment"] if s["current_status"] == "EXPIRED"}
        ins_lines = {(i["shipment_id"], i["return_line_id"]) for i in t["inspection"]}
        lines_by_rma_ship = defaultdict(list)
        for s in t["shipment_line"]:
            lines_by_rma_ship[idx["ship"][s["shipment_id"]]["rma_id"]].append((s["shipment_id"], s["return_line_id"]))
        for r in t["return_request"]:
            n += 1
            st, rid = r["current_status"], r["rma_id"]
            auth = idx["auth_by_rma"].get(rid)
            if (auth is None) != (st == "SUBMITTED"):
                v.append((rid, "authorization presence vs status"))
            if st == "REFUNDED" and rid not in paid_rmas:
                v.append((rid, "REFUNDED without PAID refund"))
            if st == "EXCHANGED" and rid not in exch_rmas:
                v.append((rid, "EXCHANGED without exchange order"))
            if st == "EXPIRED" and rid not in expired_rmas:
                v.append((rid, "EXPIRED without expired label"))
            if st == "REJECTED" and auth["approved_qty_total"] != 0:
                v.append((rid, "REJECTED with approved qty"))
            if st in ("INSPECTED", "REFUNDED", "EXCHANGED", "CLOSED_NO_REFUND"):
                if any(k not in ins_lines for k in lines_by_rma_ship[rid]):
                    v.append((rid, "closed before all lines inspected"))
        self.check("lifecycle", "Lifecycle transitions legal and statuses derived from history", n, v,
                   "append-only status_event; current_status = last event")

    # -------------------------------------------------------------- duplicates
    def duplicates(self):
        t = self.t
        v, n = [], 0
        paid_by_rma = defaultdict(list)
        keys = defaultdict(list)
        for r in sorted(t["refund"], key=lambda r: (r["requested_at"], r["refund_id"])):
            n += 1
            if r["current_status"] in ("PAID", "REQUESTED"):
                paid_by_rma[r["rma_id"]].append(r)
                keys[r["idempotency_key"]].append(r)
            elif r["current_status"] == "BLOCKED_DUPLICATE" and r["paid_amount"] != 0:
                v.append((r["refund_id"], "blocked duplicate has payout"))
        for rs in paid_by_rma.values():
            v += [(r["refund_id"], f"extra payout for {r['rma_id']}") for r in rs[1:]]
        for k, rs in keys.items():
            v += [(r["refund_id"], f"idempotency key {k} reused") for r in rs[1:]]
        blocked = [r for r in t["refund"] if r["current_status"] == "BLOCKED_DUPLICATE"]
        live_keys = {r["idempotency_key"] for r in t["refund"] if r["current_status"] != "BLOCKED_DUPLICATE"}
        for r in blocked:
            n += 1
            if r["idempotency_key"] not in live_keys:
                v.append((r["refund_id"], "blocked attempt without original"))
        seen = Counter((rl["rma_id"], rl["order_line_id"]) for rl in t["return_line"])
        v += [(f"{k[0]}", f"order line {k[1]} repeated in RMA") for k, c in seen.items() if c > 1]
        ev = Counter((e["entity_type"], e["entity_id"], e["to_status"]) for e in t["status_event"])
        v += [(k[1], f"duplicate {k[2]} event") for k, c in ev.items() if c > 1]
        self.check("duplicates", "Duplicate payouts blocked; no duplicate lines or events", n, v,
                   "<= 1 payout per RMA; idempotency keys unique")

    # ---------------------------------------------------------- business rules
    def business_rules(self):
        findings = run_audit(self.t)
        self.findings = findings
        by_type = defaultdict(list)
        for f in findings:
            by_type[f["issue_type"]].append((f["entity_id"], f["detail"]))
        names = {
            "Eligibility decisions follow policy": ["LATE_APPROVED_WITHOUT_OVERRIDE", "QTY_EXCEEDS_PURCHASED",
                                                    "ELIGIBILITY_MISMATCH"],
            "Refund math follows paid price, discounts, tax and fees": ["REFUND_EXCEEDS_PAID", "REFUND_CALC_MISMATCH"],
            "Duplicate payouts detected": ["DUPLICATE_REFUND"],
            "Disposition follows inspection and matrix": ["RESTOCK_BEFORE_INSPECTION", "DISPOSITION_BEFORE_INSPECTION",
                                                          "DISPOSITION_RULE_MISMATCH", "DISPOSITION_QTY_MISMATCH"],
        }
        counts = {"Eligibility decisions follow policy": len(self.t["authorization_line"]),
                  "Refund math follows paid price, discounts, tax and fees": len(self.t["refund"]),
                  "Duplicate payouts detected": len(self.t["refund"]),
                  "Disposition follows inspection and matrix": len(self.t["inventory_disposition"])}
        for name, types in names.items():
            self.check("business_rules", name, counts[name], [x for ty in types for x in by_type[ty]],
                       "independent re-derivation by audit.py")

    def summary(self):
        status = "FAIL" if any(r["status"] == "FAIL" for r in self.results) else "PASS"
        return {"overall_status": status, "checks": self.results,
                "totals": {"checks": len(self.results),
                           "passed": sum(r["status"] != "FAIL" for r in self.results),
                           "labelled_violations": sum(r["labelled"] for r in self.results),
                           "unlabelled_violations": sum(r["unlabelled"] for r in self.results)}}


def to_markdown(summary, manifest=None):
    out = ["# Validation summary", ""]
    if manifest:
        out += [f"Dataset: seed `{manifest['seed']}`, scale `{manifest['scale']}`, as-of `{manifest['as_of']}`", ""]
    tot = summary["totals"]
    out += [f"**Overall: {summary['overall_status']}**: {tot['passed']}/{tot['checks']} checks passed, "
            f"{tot['unlabelled_violations']} unlabelled violations, {tot['labelled_violations']} violations "
            "explained by labelled ground-truth anomalies.", "",
            "| Category | Check | Rows checked | Violations | Labelled | Unlabelled | Status |",
            "|---|---|---:|---:|---:|---:|---|"]
    for r in summary["checks"]:
        out.append(f"| {r['category']} | {r['check']} | {r['rows_checked']:,} | {r['violations']} | {r['labelled']} "
                   f"| {r['unlabelled']} | {r['status']} |")
    out += ["", "`PASS_WITH_LABELLED_EXCEPTIONS` means every violation found is a deliberately injected anomaly "
            "recorded in `ground_truth/ground_truth_anomalies.csv`.", ""]
    return "\n".join(out)
