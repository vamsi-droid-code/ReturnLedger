"""Score the audit's findings and the recorded decisions against ground truth."""
from collections import defaultdict

from .money import parse


def _prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 1.0
    r = tp / (tp + fn) if tp + fn else 1.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return round(p, 4), round(r, 4), round(f, 4)


def evaluate(tables, findings, gt_anomalies, gt_labels):
    found = {(f["issue_type"], f["entity_id"]) for f in findings}
    truth = {(a["issue_type"], a["entity_id"]) for a in gt_anomalies}
    per_type = {}
    for issue in sorted({k[0] for k in found | truth}):
        f = {k for k in found if k[0] == issue}
        g = {k for k in truth if k[0] == issue}
        tp, fp, fn = len(f & g), len(f - g), len(g - f)
        p, r, f1 = _prf(tp, fp, fn)
        per_type[issue] = {"ground_truth": len(g), "detected": len(f), "tp": tp, "fp": fp, "fn": fn,
                           "precision": p, "recall": r, "f1": f1}
    tp, fp, fn = len(found & truth), len(found - truth), len(truth - found)
    p, r, f1 = _prf(tp, fp, fn)

    al = {a["return_line_id"]: a for a in tables["authorization_line"]}
    dec = defaultdict(int)
    for lab in gt_labels:
        rec = al.get(lab["return_line_id"])
        if rec is None:
            continue
        ok = (rec["line_decision"], str(rec["approved_qty"]), rec["decision_reason"]) == (
            lab["expected_line_decision"], lab["expected_approved_qty"], lab["expected_decision_reason"])
        group = "anomalous" if lab["is_anomaly"] == "true" else "clean"
        dec[f"{group}_total"] += 1
        dec[f"{group}_match"] += ok

    disp = defaultdict(list)
    for d in tables["inventory_disposition"]:
        disp[d["return_line_id"]].append(d["disposition"])
    first_refund = {r["refund_id"] for r in tables["refund"] if r["attempt_seq"] == 1}
    paid_line = defaultdict(int)
    has_refund = set()
    for rf in tables["refund_line"]:
        if rf["refund_id"] in first_refund:
            paid_line[rf["return_line_id"]] += rf["line_refund_amount"]
            has_refund.add(rf["return_line_id"])
    dmatch = dtotal = rmatch = rtotal = 0
    for lab in gt_labels:
        if lab["is_anomaly"] == "true":
            continue
        if lab["expected_disposition"]:
            dtotal += 1
            dmatch += ";".join(disp.get(lab["return_line_id"], [])) == lab["expected_disposition"]
        if lab["expected_line_refund_amount"]:
            rtotal += 1
            rmatch += lab["return_line_id"] in has_refund and \
                paid_line[lab["return_line_id"]] == parse(lab["expected_line_refund_amount"])

    refunds = {r["refund_id"]: r for r in tables["refund"]}
    leakage = defaultdict(int)
    for a in gt_anomalies:
        if a["issue_type"] == "DUPLICATE_REFUND":
            leakage["duplicate_payouts"] += refunds[a["entity_id"]]["paid_amount"]
        elif a["issue_type"] == "REFUND_EXCEEDS_PAID":
            leakage["over_refunds"] += refunds[a["entity_id"]]["refund_amount"] - parse(a["expected_value"].split("=")[1])
    blocked = [r for r in tables["refund"] if r["current_status"] == "BLOCKED_DUPLICATE"]

    def rate(m, n):
        return round(m / n, 4) if n else None

    return {
        "anomaly_detection": {"micro": {"tp": tp, "fp": fp, "fn": fn, "precision": p, "recall": r, "f1": f1},
                              "per_issue_type": per_type},
        "decision_conformance": {
            "clean_lines": dec["clean_total"], "clean_match_rate": rate(dec["clean_match"], dec["clean_total"]),
            "anomalous_lines": dec["anomalous_total"],
            "anomalous_lines_deviating": dec["anomalous_total"] - dec["anomalous_match"],
        },
        "disposition_conformance": {"lines": dtotal, "match_rate": rate(dmatch, dtotal)},
        "refund_conformance": {"lines": rtotal, "match_rate": rate(rmatch, rtotal)},
        "financial_impact_usd": {
            "leakage_from_injected_anomalies": round(sum(leakage.values()) / 100, 2),
            "duplicate_payouts": round(leakage["duplicate_payouts"] / 100, 2),
            "over_refunds": round(leakage["over_refunds"] / 100, 2),
            "duplicate_attempts_blocked": len(blocked),
            "amount_protected_by_idempotency": round(sum(r["refund_amount"] for r in blocked) / 100, 2),
        },
    }
