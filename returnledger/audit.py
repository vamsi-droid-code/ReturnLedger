"""Independent audit / exception detector.

Reads only the exported input tables (never ground truth), re-derives what the policy says
should have happened and raises a classified finding for every deviation. Its output is then
scored against ground truth in evaluate.py.
"""
from . import policy as P

ACTIONS = {
    "LATE_APPROVED_WITHOUT_OVERRIDE": ("MEDIUM", "Hold refund; require ops-manager override or reject the line"),
    "QTY_EXCEEDS_PURCHASED": ("HIGH", "Cap authorization at purchased qty; investigate phantom inventory"),
    "ELIGIBILITY_MISMATCH": ("MEDIUM", "Re-run eligibility rules and correct the authorization"),
    "DUPLICATE_REFUND": ("HIGH", "Block/claw back the second payout; enforce idempotency per RMA"),
    "REFUND_EXCEEDS_PAID": ("HIGH", "Reverse excess; refund cannot exceed net paid + tax"),
    "REFUND_CALC_MISMATCH": ("MEDIUM", "Recalculate refund from paid price, discounts, tax and fees"),
    "RESTOCK_BEFORE_INSPECTION": ("HIGH", "Pull units from sellable stock and inspect"),
    "DISPOSITION_BEFORE_INSPECTION": ("MEDIUM", "Re-sequence disposition after inspection"),
    "DISPOSITION_RULE_MISMATCH": ("LOW", "Re-route units per disposition matrix"),
    "DISPOSITION_QTY_MISMATCH": ("MEDIUM", "Reconcile disposed qty with received qty"),
}


def policies_from_table(rows):
    return [P.Policy(r["policy_id"], r["category"], r["version"], r["effective_from"], r["effective_to"],
                     r["return_window_days"], r["returnable"], r["opened_returnable"], r["restocking_fee_rate"],
                     r["merchant_fault_override"]) for r in rows]


def run_audit(t):
    findings = []

    def flag(issue, entity_type, entity_id, rma_id, detail):
        severity, action = ACTIONS[issue]
        findings.append({"finding_id": f"F-{len(findings) + 1:05d}", "issue_type": issue, "severity": severity,
                         "entity_type": entity_type, "entity_id": entity_id, "rma_id": rma_id, "detail": detail,
                         "recommended_action": action})

    policies = policies_from_table(t["return_policy"])
    orders = {o["order_id"]: o for o in t["orders"]}
    order_lines = {ol["order_line_id"]: ol for ol in t["order_line"]}
    customers = {c["customer_id"]: c for c in t["customer"]}
    requests = {r["rma_id"]: r for r in t["return_request"]}
    lines_by_rma = {}
    for rl in t["return_line"]:
        lines_by_rma.setdefault(rl["rma_id"], []).append(rl)
    rl_by_id = {rl["return_line_id"]: rl for rl in t["return_line"]}
    auth_line = {al["return_line_id"]: al for al in t["authorization_line"]}

    def pol(ol):
        return P.policy_for(policies, ol["category"], orders[ol["order_id"]]["placed_at"].date())

    # 1. Eligibility conformance, chronological so prior approvals are known.
    prior = {}
    for req in sorted(t["return_request"], key=lambda r: (r["requested_at"], r["rma_id"])):
        order = orders[req["order_id"]]
        tier = customers[req["customer_id"]]["loyalty_tier"]
        for rl in lines_by_rma[req["rma_id"]]:
            al = auth_line.get(rl["return_line_id"])
            if al is None:
                continue
            ol = order_lines[rl["order_line_id"]]
            done = prior.get(ol["order_line_id"], 0)
            exp = P.decide_line(policy=pol(ol), loyalty_tier=tier, delivered_date=order["delivered_at"].date(),
                                requested_date=req["requested_at"].date(), purchased_qty=ol["qty"],
                                prior_approved_qty=done, requested_qty=rl["requested_qty"],
                                return_reason=rl["return_reason"], item_opened=rl["item_opened"],
                                is_final_sale=ol["is_final_sale"], late_override=req["late_override_flag"])
            prior[ol["order_line_id"]] = done + al["approved_qty"]
            if (al["approved_qty"], al["line_decision"], al["decision_reason"]) == (
                    exp.approved_qty, exp.line_decision, exp.decision_reason):
                continue
            if al["approved_qty"] > ol["qty"] - done:
                flag("QTY_EXCEEDS_PURCHASED", "authorization_line", al["authorization_line_id"], req["rma_id"],
                     f"approved {al['approved_qty']} > purchased {ol['qty']} - prior {done}")
            elif exp.decision_reason == "REJECT_LATE" and al["approved_qty"] > 0:
                flag("LATE_APPROVED_WITHOUT_OVERRIDE", "authorization_line", al["authorization_line_id"],
                     req["rma_id"], f"{exp.days_since_delivery} days > window {exp.effective_window_days}, no override")
            else:
                flag("ELIGIBILITY_MISMATCH", "authorization_line", al["authorization_line_id"], req["rma_id"],
                     f"recorded {al['line_decision']}/{al['decision_reason']} expected "
                     f"{exp.line_decision}/{exp.decision_reason}")

    # 2. Refunds: duplicates first, then recompute amounts in the order RMAs were processed.
    inspections = {i["inspection_id"]: i for i in t["inspection"]}
    lines_by_refund = {}
    for rf in t["refund_line"]:
        lines_by_refund.setdefault(rf["refund_id"], []).append(rf)
    refunds_by_rma = {}
    for ref in t["refund"]:
        refunds_by_rma.setdefault(ref["rma_id"], []).append(ref)
    refunded, shipping_refunded = {}, set()
    for rma_id in sorted(refunds_by_rma, key=lambda r: (requests[r]["requested_at"], r)):
        req = requests[rma_id]
        order = orders[req["order_id"]]
        refs = sorted(refunds_by_rma[rma_id], key=lambda r: (r["requested_at"], r["refund_id"]))
        payouts = [r for r in refs if r["current_status"] in ("PAID", "REQUESTED")]
        for dup in payouts[1:]:
            flag("DUPLICATE_REFUND", "refund", dup["refund_id"], rma_id,
                 f"second payout {dup['paid_amount'] / 100:.2f} after {payouts[0]['refund_id']}")
        for ref in refs:
            if ref["current_status"] == "BLOCKED_DUPLICATE" and ref["paid_amount"] != 0:
                flag("DUPLICATE_REFUND", "refund", ref["refund_id"], rma_id, "blocked attempt shows a payout")
        if not payouts:
            continue
        ref = payouts[0]
        exceeded, mismatch, any_mf, lines_total = False, False, False, 0
        for rf in lines_by_refund.get(ref["refund_id"], []):
            ins = inspections[rf["inspection_id"]]
            rl = rl_by_id[rf["return_line_id"]]
            ol = order_lines[rf["order_line_id"]]
            done = refunded.get(ol["order_line_id"], 0)
            exp = P.refund_line(net_amount=ol["net_amount"], tax_amount=ol["tax_amount"], purchased_qty=ol["qty"],
                                refund_qty=ins["received_qty"], condition=ins["condition_grade"],
                                attribution=ins["damage_attribution"], return_reason=rl["return_reason"],
                                restocking_fee_rate=pol(ol).restocking_fee_rate, already_refunded=done)
            any_mf = any_mf or P.merchant_fault_confirmed(ins["condition_grade"], ins["damage_attribution"],
                                                          rl["return_reason"])
            if rf["line_refund_amount"] > ol["line_total"] - done:
                exceeded = True
            recorded = (rf["merchandise_amount"], rf["tax_amount"], rf["restocking_fee"], rf["damage_deduction"],
                        rf["cap_adjustment"], rf["line_refund_amount"], rf["refund_qty"])
            expected = (exp.merchandise_amount, exp.tax_amount, exp.restocking_fee, exp.damage_deduction,
                        exp.cap_adjustment, exp.line_refund_amount, ins["received_qty"])
            mismatch = mismatch or recorded != expected
            refunded[ol["order_line_id"]] = done + rf["line_refund_amount"]
            lines_total += exp.line_refund_amount
        ship, fee, amount = P.refund_header(lines_amount=lines_total, any_merchant_fault=any_mf,
                                            shipping_fee=order["shipping_fee"],
                                            shipping_already_refunded=order["order_id"] in shipping_refunded,
                                            refund_method=ref["refund_method"], return_channel=req["return_channel"])
        if ship:
            shipping_refunded.add(order["order_id"])
        if exceeded:
            flag("REFUND_EXCEEDS_PAID", "refund", ref["refund_id"], rma_id,
                 f"refund {ref['refund_amount'] / 100:.2f} vs policy {amount / 100:.2f}; a line exceeds amount paid")
        elif mismatch or (ref["shipping_refund"], ref["return_label_fee"], ref["refund_amount"]) != (ship, fee, amount):
            flag("REFUND_CALC_MISMATCH", "refund", ref["refund_id"], rma_id,
                 f"refund {ref['refund_amount'] / 100:.2f} expected {amount / 100:.2f}")

    # 3. Disposition controls inventory movement: only after inspection, per the matrix.
    rma_of_line = {rl["return_line_id"]: rl["rma_id"] for rl in t["return_line"]}
    for d in t["inventory_disposition"]:
        ins = inspections.get(d["inspection_id"])
        rma_id = rma_of_line[d["return_line_id"]]
        if ins is None or d["decided_at"] < ins["inspected_at"]:
            issue = "RESTOCK_BEFORE_INSPECTION" if d["disposition"] == "RESTOCK" else "DISPOSITION_BEFORE_INSPECTION"
            flag(issue, "inventory_disposition", d["disposition_id"], rma_id,
                 f"decided {d['decided_at']} before inspection {ins['inspected_at'] if ins else 'missing'}")
            continue
        ol = order_lines[rl_by_id[d["return_line_id"]]["order_line_id"]]
        if d["disposition"] != P.decide_disposition(ol["category"], ins["condition_grade"], ol["unit_price"]):
            flag("DISPOSITION_RULE_MISMATCH", "inventory_disposition", d["disposition_id"], rma_id,
                 f"{d['disposition']} for {ins['condition_grade']} {ol['category']}")
        if d["qty"] != ins["received_qty"]:
            flag("DISPOSITION_QTY_MISMATCH", "inventory_disposition", d["disposition_id"], rma_id,
                 f"qty {d['qty']} vs received {ins['received_qty']}")
    return findings
