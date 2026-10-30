"""Business KPIs and scenario coverage, computed only from the exported tables."""
from collections import Counter, defaultdict

from . import config as C
from . import policy as P


def pct(n, d):
    return round(100 * n / d, 2) if d else 0.0


def usd(cents):
    return round(cents / 100, 2)


def percentile(values, q):
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * q
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (k - lo), 2)


def compute(t):
    orders = {o["order_id"]: o for o in t["orders"]}
    ol = {x["order_line_id"]: x for x in t["order_line"]}
    sales = [o for o in t["orders"] if o["order_type"] == "SALE"]
    sale_lines = [x for x in t["order_line"] if orders[x["order_id"]]["order_type"] == "SALE"]
    rl_by_id = {r["return_line_id"]: r for r in t["return_line"]}
    rma = {r["rma_id"]: r for r in t["return_request"]}
    al = {a["return_line_id"]: a for a in t["authorization_line"]}
    auth = {a["rma_id"]: a for a in t["return_authorization"]}
    ins_by_line = defaultdict(list)
    for i in t["inspection"]:
        ins_by_line[i["return_line_id"]].append(i)

    units_sold = sum(x["qty"] for x in sale_lines)
    gmv = sum(o["order_total"] for o in sales)

    # --- category view
    cat = defaultdict(lambda: Counter())
    for x in sale_lines:
        cat[x["category"]]["lines_sold"] += 1
        cat[x["category"]]["units_sold"] += x["qty"]
    for r in t["return_line"]:
        c = ol[r["order_line_id"]]["category"]
        cat[c]["return_lines"] += 1
        cat[c]["units_requested"] += r["requested_qty"]
        a = al.get(r["return_line_id"])
        if a:
            cat[c]["decided"] += 1
            cat[c]["approved"] += a["line_decision"] != "REJECTED"
            cat[c]["units_approved"] += a["approved_qty"]
    categories = []
    for c in C.CATEGORIES:
        x = cat[c]
        categories.append({"category": c, "units_sold": x["units_sold"], "return_lines": x["return_lines"],
                           "units_requested": x["units_requested"],
                           "return_rate_pct": pct(x["units_requested"], x["units_sold"]),
                           "approval_rate_pct": pct(x["approved"], x["decided"])})

    # --- scenario coverage (normal, boundary, failure and exception paths)
    lines_per_ol = Counter(r["order_line_id"] for r in t["return_line"])
    rmas_per_order = Counter(r["order_id"] for r in t["return_request"])
    late = late_override = boundary = partial = over = 0
    for r in t["return_line"]:
        a = al.get(r["return_line_id"])
        if not a:
            continue
        o = ol[r["order_line_id"]]
        if a["days_since_delivery"] > a["effective_window_days"]:
            late += 1
            late_override += a["override_applied"]
        boundary += a["days_since_delivery"] == a["effective_window_days"]
        partial += r["requested_qty"] < o["qty"] - a["prior_approved_qty"]
        over += r["requested_qty"] > o["qty"] - a["prior_approved_qty"]
    reasons = Counter(a["decision_reason"] for a in t["authorization_line"])
    ship_status = Counter(s["current_status"] for s in t["return_shipment"])
    ships_per_rma = Counter(s["rma_id"] for s in t["return_shipment"])
    sl = {(s["shipment_id"], s["return_line_id"]): s["shipped_qty"] for s in t["shipment_line"]}
    cond = Counter(i["condition_grade"] for i in t["inspection"])
    attribution = Counter(i["damage_attribution"] for i in t["inspection"] if i["condition_grade"] == "DAMAGED")
    shortages = sum(i["received_qty"] < sl[(i["shipment_id"], i["return_line_id"])] for i in t["inspection"])
    rma_status = Counter(r["current_status"] for r in t["return_request"])
    refunds_paid = [r for r in t["refund"] if r["current_status"] == "PAID"]
    exch_fallback = sum(1 for r in t["refund"] if r["attempt_seq"] == 1 and rma[r["rma_id"]]["resolution_type"] == "EXCHANGE")
    coverage = {
        "partial_return_lines": partial,
        "over_requested_lines": over,
        "late_request_lines": late,
        "late_lines_with_manager_override": late_override,
        "boundary_day_equals_window_lines": boundary,
        "orders_with_multiple_rmas": sum(1 for v in rmas_per_order.values() if v > 1),
        "order_lines_on_multiple_rmas": sum(1 for v in lines_per_ol.values() if v > 1),
        "excluded_category_rejections": reasons["REJECT_EXCLUDED_CATEGORY"],
        "final_sale_rejections": reasons["REJECT_FINAL_SALE"],
        "hygiene_rejections": reasons["REJECT_HYGIENE_OPENED"],
        "qty_capped_lines": reasons["QTY_CAPPED"],
        "split_shipment_rmas": sum(1 for v in ships_per_rma.values() if v > 1),
        "missing_shipments_label_expired": ship_status["EXPIRED"],
        "lost_in_transit": ship_status["LOST"],
        "short_shipped_inspections": shortages,
        "damaged_goods_inspections": cond["DAMAGED"],
        "damaged_by_customer": attribution["CUSTOMER"],
        "damaged_by_carrier": attribution["CARRIER"],
        "defective_inspections": cond["DEFECTIVE"],
        "not_original_item_inspections": cond["NOT_ORIGINAL_ITEM"],
        "exchanges_completed": rma_status["EXCHANGED"],
        "exchange_requests_fallback_to_refund": exch_fallback,
        "store_credit_refunds": sum(1 for r in refunds_paid if r["refund_method"] == "STORE_CREDIT"),
        "duplicate_refund_attempts_blocked": sum(1 for r in t["refund"] if r["current_status"] == "BLOCKED_DUPLICATE"),
        "closed_no_refund": rma_status["CLOSED_NO_REFUND"],
    }

    # --- money
    rfl = [x for x in t["refund_line"]]
    paid_ids = {r["refund_id"] for r in refunds_paid}
    paid_lines = [x for x in rfl if x["refund_id"] in paid_ids]
    returned_value = sum(x["merchandise_amount"] + x["tax_amount"] for x in paid_lines)
    paid_total = sum(r["paid_amount"] for r in refunds_paid)
    money = {
        "gross_order_value_usd": usd(gmv),
        "refunds_paid_count": len(refunds_paid),
        "refunds_paid_usd": usd(paid_total),
        "refunds_as_pct_of_order_value": pct(paid_total, gmv),
        "avg_refund_usd": usd(paid_total / len(refunds_paid)) if refunds_paid else 0,
        "restocking_fees_usd": usd(sum(x["restocking_fee"] for x in paid_lines)),
        "damage_deductions_usd": usd(sum(x["damage_deduction"] for x in paid_lines)),
        "return_label_fees_usd": usd(sum(r["return_label_fee"] for r in refunds_paid)),
        "shipping_refunded_usd": usd(sum(r["shipping_refund"] for r in refunds_paid)),
        "refund_recovery_ratio_pct": pct(sum(x["line_refund_amount"] for x in paid_lines), returned_value),
    }

    # --- cycle times
    ev = defaultdict(dict)
    for e in t["status_event"]:
        if e["entity_type"] == "RETURN_REQUEST":
            ev[e["entity_id"]].setdefault(e["to_status"], e["event_ts"])
    decide_h = [(a["decided_at"] - rma[a["rma_id"]]["requested_at"]).total_seconds() / 3600 for a in t["return_authorization"]]
    to_refund_d = [(v["REFUNDED"] - v["SUBMITTED"]).total_seconds() / 86400 for v in ev.values() if "REFUNDED" in v]
    recv_insp_h = []
    ships = {s["shipment_id"]: s for s in t["return_shipment"]}
    for i in t["inspection"]:
        recv_insp_h.append((i["inspected_at"] - ships[i["shipment_id"]]["received_at"]).total_seconds() / 3600)
    cycle = {
        "request_to_decision_hours_p50": percentile(decide_h, 0.5),
        "request_to_decision_hours_p90": percentile(decide_h, 0.9),
        "received_to_inspected_hours_p50": percentile(recv_insp_h, 0.5),
        "request_to_refund_days_p50": percentile(to_refund_d, 0.5),
        "request_to_refund_days_p90": percentile(to_refund_d, 0.9),
    }

    # --- disposition and inventory recovery
    disp = defaultdict(lambda: Counter())
    mov = {m["disposition_id"]: m for m in t["inventory_movement"]}
    for d in t["inventory_disposition"]:
        disp[d["disposition"]]["qty"] += d["qty"]
        disp[d["disposition"]]["value"] += mov[d["disposition_id"]]["movement_value"]
    total_value = sum(v["value"] for v in disp.values())
    recovered = sum(v["value"] * P.RECOVERY_FACTOR[k] for k, v in disp.items())
    disposition = {
        "by_disposition": {k: {"units": disp[k]["qty"], "cost_value_usd": usd(disp[k]["value"])}
                           for k in ["RESTOCK", "REFURBISH", "QUARANTINE", "SCRAP"]},
        "inventory_recovery_rate_pct": pct(recovered, total_value),
    }

    approved_lines = sum(1 for a in t["authorization_line"] if a["line_decision"] != "REJECTED")
    return {
        "volume": {
            "customers": len(t["customer"]), "sales_orders": len(sales),
            "exchange_orders": len(t["orders"]) - len(sales), "order_lines": len(t["order_line"]),
            "units_sold": units_sold, "return_requests": len(t["return_request"]),
            "return_lines": len(t["return_line"]), "status_events": len(t["status_event"]),
        },
        "returns": {
            "order_return_rate_pct": pct(len({r["order_id"] for r in t["return_request"]}), len(sales)),
            "unit_return_rate_pct": pct(sum(r["requested_qty"] for r in t["return_line"]), units_sold),
            "line_approval_rate_pct": pct(approved_lines, len(t["authorization_line"])),
            "authorization_status": dict(Counter(a["decision_status"] for a in t["return_authorization"])),
            "decision_reasons": dict(reasons),
            "resolution_requested": dict(Counter(r["resolution_type"] for r in t["return_request"])),
            "pending_decision": sum(1 for r in t["return_request"] if r["rma_id"] not in auth),
        },
        "categories": categories,
        "coverage": coverage,
        "money": money,
        "cycle_times": cycle,
        "inspection_conditions": dict(cond),
        "disposition": disposition,
        "pipeline": {"rma_status": dict(rma_status), "shipment_status": dict(ship_status)},
    }
