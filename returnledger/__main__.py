"""Command line interface.

    python -m returnledger run --scale starter        # generate + validate + audit + evaluate + report
    python -m returnledger run --scale full
    python -m returnledger reproduce --scale starter  # generate twice, compare checksums
    python -m returnledger robustness --scale full    # several seeds, clean + anomalies, zero unlabelled
    python -m returnledger explain --rma RMA-2026-000123 --data data/starter
    python -m returnledger serve --scale full          # web UI at http://127.0.0.1:8000
    python -m returnledger generate | validate | audit | report | docs
"""
import argparse
import csv
import json
import os
import shutil
import sys
import time

from . import config as C
from . import storage
from .audit import run_audit
from .evaluate import evaluate
from .generator import generate
from .metrics import compute
from .report import render, data_dictionary_md
from .validate import Validator, to_markdown

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FINDING_COLS = ["finding_id", "issue_type", "severity", "entity_type", "entity_id", "rma_id", "detail",
                "recommended_action"]


def resolve_scale(value):
    if value in C.SCALES:
        return value, C.SCALES[value]
    return f"scale_{value}", float(value)


def data_dir_for(args):
    if getattr(args, "data", None):
        return args.data
    name, _ = resolve_scale(args.scale)
    return os.path.join(ROOT, "data", name)


def _manifest(data_dir):
    with open(os.path.join(data_dir, "manifest.json"), encoding="utf-8") as fh:
        return json.load(fh)


# ------------------------------------------------------------------- commands
def cmd_generate(args):
    name, scale = resolve_scale(args.scale)
    out = data_dir_for(args)
    formats = tuple(args.formats.split(","))
    start = time.time()
    g = generate(seed=args.seed, scale=scale)
    command = f"python -m returnledger generate --scale {args.scale} --seed {args.seed}"
    manifest = storage.export(g, out, formats=formats, command=command)
    print(f"[generate] seed={args.seed} scale={scale} -> {os.path.relpath(out, ROOT)} ({time.time() - start:.1f}s)")
    for k, n in manifest["row_counts"].items():
        print(f"  {k:<24}{n:>9,}")
    print(f"  ground truth anomalies  {len(g.gt_anomalies):>9,}")
    return out


def cmd_validate(args, quiet=False):
    data = data_dir_for(args)
    tables = storage.load_tables(data)
    gt, _ = storage.load_ground_truth(data)
    manifest = _manifest(data)
    v = Validator(tables, gt, data, manifest["target_volume"])
    summary = v.run()
    reports = os.path.join(data, "reports")
    storage.write_json(os.path.join(reports, "validation_summary.json"), summary)
    with open(os.path.join(reports, "validation_summary.md"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(to_markdown(summary, manifest))
    storage.write_csv(os.path.join(reports, "audit_findings.csv"), v.findings, FINDING_COLS)
    if not quiet:
        print(f"[validate] {os.path.relpath(data, ROOT)}")
        for r in summary["checks"]:
            print(f"  {r['status']:<30} {r['category']:<15} {r['check']}  "
                  f"(violations={r['violations']}, labelled={r['labelled']})")
        print(f"  OVERALL: {summary['overall_status']}")
    return summary, v.findings, tables


def cmd_audit(args):
    data = data_dir_for(args)
    tables = storage.load_tables(data)
    findings = run_audit(tables)
    gt, labels = storage.load_ground_truth(data)
    ev = evaluate(tables, findings, gt, labels)
    reports = os.path.join(data, "reports")
    storage.write_csv(os.path.join(reports, "audit_findings.csv"), findings, FINDING_COLS)
    storage.write_json(os.path.join(reports, "evaluation.json"), ev)
    print(f"[audit] {len(findings)} findings")
    for k, x in ev["anomaly_detection"]["per_issue_type"].items():
        print(f"  {k:<32} truth={x['ground_truth']:<4} detected={x['detected']:<4} "
              f"precision={x['precision']:.2%} recall={x['recall']:.2%}")
    return ev


def cmd_report(args, summary=None, ev=None, tables=None):
    data = data_dir_for(args)
    tables = tables or storage.load_tables(data)
    reports = os.path.join(data, "reports")
    if summary is None:
        with open(os.path.join(reports, "validation_summary.json"), encoding="utf-8") as fh:
            summary = json.load(fh)
    if ev is None:
        with open(os.path.join(reports, "evaluation.json"), encoding="utf-8") as fh:
            ev = json.load(fh)
    m = compute(tables)
    storage.write_json(os.path.join(reports, "metrics.json"), m)
    path = os.path.join(reports, "report.html")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render(m, summary, ev, _manifest(data)))
    print(f"[report] {os.path.relpath(path, ROOT)}")
    return m


def cmd_run(args):
    args.data = None
    out = cmd_generate(args)
    args.data = out
    summary, findings, tables = cmd_validate(args)
    ev = cmd_audit(args)
    m = cmd_report(args, summary, ev, tables)
    print("\n=== ReturnLedger summary ===")
    print(f"  validation          : {summary['overall_status']} ({summary['totals']['passed']}/"
          f"{summary['totals']['checks']} checks, {summary['totals']['unlabelled_violations']} unlabelled violations)")
    micro = ev["anomaly_detection"]["micro"]
    print(f"  anomaly detection   : precision {micro['precision']:.2%}, recall {micro['recall']:.2%}")
    print(f"  clean decisions     : {ev['decision_conformance']['clean_match_rate']:.2%} match policy")
    print(f"  approval rate       : {m['returns']['line_approval_rate_pct']}% of lines")
    print(f"  refunds paid        : ${m['money']['refunds_paid_usd']:,.2f}")
    print(f"  open report         : {os.path.relpath(os.path.join(out, 'reports', 'report.html'), ROOT)}")
    return 0 if summary["overall_status"] == "PASS" else 1


def cmd_reproduce(args):
    name, scale = resolve_scale(args.scale)
    tmp = os.path.join(ROOT, ".tmp", "reproduce")
    shutil.rmtree(tmp, ignore_errors=True)
    runs = []
    for label in ("run_a", "run_b"):
        g = generate(seed=args.seed, scale=scale)
        manifest = storage.export(g, os.path.join(tmp, label), formats=("csv", "json", "sql"))
        runs.append({f["path"]: f for f in manifest["files"]})
    rows, identical = [], True
    for path in sorted(runs[0]):
        a, b = runs[0][path], runs[1].get(path, {})
        same = a["sha256"] == b.get("sha256") and a["rows"] == b.get("rows")
        identical &= same
        rows.append({"file": path, "rows_run_a": a["rows"], "rows_run_b": b.get("rows"),
                     "sha256_run_a": a["sha256"], "sha256_run_b": b.get("sha256"), "identical": same})
    result = {"seed": args.seed, "scale": scale, "files_compared": len(rows), "all_identical": identical, "files": rows}
    reports = os.path.join(ROOT, "data", name, "reports")
    storage.write_json(os.path.join(reports, "reproducibility.json"), result)
    md = ["# Reproducibility check", "",
          f"Generated the `{name}` dataset twice with seed `{args.seed}` into separate folders and compared every "
          f"exported file. **Result: {'IDENTICAL' if identical else 'DIFFERENT'}** ({len(rows)} files).", "",
          "| File | Rows (run A) | Rows (run B) | SHA-256 (first 16) | Identical |", "|---|---:|---:|---|---|"]
    md += [f"| {r['file']} | {r['rows_run_a']:,} | {r['rows_run_b']:,} | `{r['sha256_run_a'][:16]}` | "
           f"{'yes' if r['identical'] else 'NO'} |" for r in rows]
    with open(os.path.join(reports, "reproducibility.md"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(md) + "\n")
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"[reproduce] {len(rows)} files compared across two runs: {'IDENTICAL' if identical else 'DIFFERENT'}")
    return 0 if identical else 1


def cmd_robustness(args):
    """Generate with several seeds, with and without anomalies, and require zero unlabelled violations."""
    name, scale = resolve_scale(args.scale)
    tmp = os.path.join(ROOT, ".tmp", "robustness")
    rows, ok = [], True
    for seed in [int(s) for s in args.seeds.split(",")]:
        for inject in (False, True):
            shutil.rmtree(tmp, ignore_errors=True)
            g = generate(seed=seed, scale=scale, inject_anomalies=inject)
            manifest = storage.export(g, tmp, formats=("csv",))
            t = storage.load_tables(tmp)
            gt, labels = storage.load_ground_truth(tmp)
            summary = Validator(t, gt, tmp, manifest["target_volume"]).run()
            micro = evaluate(t, run_audit(t), gt, labels)["anomaly_detection"]["micro"]
            passed = summary["overall_status"] == "PASS" and micro["fp"] == 0 and micro["fn"] == 0
            ok &= passed
            rows.append({"seed": seed, "anomalies": inject, "validation": summary["overall_status"],
                         "violations": summary["totals"]["labelled_violations"] + summary["totals"]["unlabelled_violations"],
                         "unlabelled": summary["totals"]["unlabelled_violations"], "ground_truth": len(gt),
                         "tp": micro["tp"], "fp": micro["fp"], "fn": micro["fn"], "passed": passed})
            print(f"  seed={seed:<9} anomalies={str(inject):<5} validation={summary['overall_status']} "
                  f"unlabelled={rows[-1]['unlabelled']} tp/fp/fn={micro['tp']}/{micro['fp']}/{micro['fn']}")
    shutil.rmtree(os.path.join(ROOT, ".tmp"), ignore_errors=True)
    reports = os.path.join(ROOT, "data", name, "reports")
    storage.write_json(os.path.join(reports, "robustness.json"), {"scale": scale, "all_passed": ok, "runs": rows})
    md = ["# Robustness check", "",
          f"Each seed is generated twice at scale {scale}: clean (no injection) and with labelled anomalies. A run "
          "passes when validation has zero unlabelled violations and the audit has zero false positives/negatives.",
          f"**Result: {'ALL PASSED' if ok else 'FAILURES'}**", "",
          "| Seed | Anomalies injected | Validation | Violations | Unlabelled | Ground truth | TP | FP | FN | Pass |",
          "|---|---|---|---:|---:|---:|---:|---:|---:|---|"]
    md += [f"| {r['seed']} | {r['anomalies']} | {r['validation']} | {r['violations']} | {r['unlabelled']} | "
           f"{r['ground_truth']} | {r['tp']} | {r['fp']} | {r['fn']} | {'yes' if r['passed'] else 'NO'} |" for r in rows]
    with open(os.path.join(reports, "robustness.md"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(md) + "\n")
    print(f"[robustness] {'ALL PASSED' if ok else 'FAILURES'}")
    return 0 if ok else 1


def cmd_explain(args):
    data = data_dir_for(args)
    t = storage.load_tables(data)
    rid = args.rma
    req = next((r for r in t["return_request"] if r["rma_id"] == rid), None)
    if req is None:
        print(f"{rid} not found in {data}")
        return 1
    order = next(o for o in t["orders"] if o["order_id"] == req["order_id"])
    cust = next(c for c in t["customer"] if c["customer_id"] == req["customer_id"])
    ol = {x["order_line_id"]: x for x in t["order_line"] if x["order_id"] == order["order_id"]}
    lines = [rl for rl in t["return_line"] if rl["rma_id"] == rid]
    al = {a["return_line_id"]: a for a in t["authorization_line"]}
    auth = next((a for a in t["return_authorization"] if a["rma_id"] == rid), None)
    usd = lambda c: f"${c / 100:,.2f}"
    print(f"{rid}  status={req['current_status']}  resolution={req['resolution_type']}  channel={req['return_channel']}")
    print(f"  order {order['order_id']} placed {order['placed_at']} delivered {order['delivered_at']} total "
          f"{usd(order['order_total'])} promo={order['promo_code']}")
    print(f"  customer {cust['customer_id']} tier={cust['loyalty_tier']}  requested {req['requested_at']}  "
          f"override={req['late_override_flag']} {req['override_reason'] or ''}")
    if auth:
        print(f"  authorization {auth['authorization_id']} {auth['decision_status']} by {auth['decided_by_role']} "
              f"at {auth['decided_at']}")
    print("  lines:")
    for rl in lines:
        o = ol[rl["order_line_id"]]
        a = al.get(rl["return_line_id"])
        dec = (f"{a['line_decision']} qty={a['approved_qty']} reason={a['decision_reason']} "
               f"days={a['days_since_delivery']}/{a['effective_window_days']} policy={a['policy_id']}") if a else "PENDING"
        print(f"    {rl['return_line_id']} {o['category']:<11} bought={o['qty']} asked={rl['requested_qty']} "
              f"reason={rl['return_reason']} opened={rl['item_opened']} paid={usd(o['line_total'])}"
              f"{' FINAL_SALE' if o['is_final_sale'] else ''}\n      -> {dec}")
    ships = [s for s in t["return_shipment"] if s["rma_id"] == rid]
    for s in ships:
        print(f"  shipment {s['shipment_id']} {s['carrier']} {s['current_status']} shipped={s['shipped_at']} "
              f"received={s['received_at']}")
    ids = {rl["return_line_id"] for rl in lines}
    disp = {d["inspection_id"]: d for d in t["inventory_disposition"]}
    for i in t["inspection"]:
        if i["return_line_id"] in ids:
            d = disp.get(i["inspection_id"])
            print(f"  inspection {i['inspection_id']} {i['return_line_id']} recv={i['received_qty']} "
                  f"{i['condition_grade']}/{i['damage_attribution']} {i['inspection_result']}"
                  + (f" -> {d['disposition_id']} {d['disposition']} at {d['decided_at']}" if d else ""))
    for r in t["refund"]:
        if r["rma_id"] == rid:
            print(f"  refund {r['refund_id']} {r['current_status']} key={r['idempotency_key']} lines="
                  f"{usd(r['lines_amount'])} +ship {usd(r['shipping_refund'])} -label {usd(r['return_label_fee'])} "
                  f"= {usd(r['refund_amount'])} paid {usd(r['paid_amount'])}")
            for x in t["refund_line"]:
                if x["refund_id"] == r["refund_id"]:
                    print(f"      {x['return_line_id']} merch {usd(x['merchandise_amount'])} tax {usd(x['tax_amount'])}"
                          f" -fee {usd(x['restocking_fee'])} -damage {usd(x['damage_deduction'])} "
                          f"-cap {usd(x['cap_adjustment'])} = {usd(x['line_refund_amount'])}")
    related = {rid, order["order_id"]} | {s["shipment_id"] for s in ships} | \
              {r["refund_id"] for r in t["refund"] if r["rma_id"] == rid}
    print("  event history:")
    for e in t["status_event"]:
        if e["entity_id"] in related:
            print(f"    {e['event_ts']}  {e['entity_type']:<16}{e['entity_id']:<18}"
                  f"{(e['from_status'] or '-'):>20} -> {e['to_status']:<20}{e['actor_role']}")
    path = os.path.join(data, "reports", "audit_findings.csv")
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8") as fh:
            hits = [f for f in csv.DictReader(fh) if f["rma_id"] == rid]
        print("  audit findings: " + ("none" if not hits else ""))
        for f in hits:
            print(f"    [{f['severity']}] {f['issue_type']} {f['entity_id']}: {f['detail']}")
    return 0


def cmd_serve(args):
    from .webapp import serve
    data = data_dir_for(args)
    if not os.path.exists(os.path.join(data, "reports", "validation_summary.json")):
        print(f"[serve] {os.path.relpath(data, ROOT)} has no reports yet. Run: python -m returnledger run --scale {args.scale}")
        return 1
    serve(data, port=args.port, open_browser=not args.no_browser)
    return 0


def cmd_docs(args):
    path = os.path.join(ROOT, "docs", "DATA_DICTIONARY.md")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(data_dictionary_md())
    sql = os.path.join(ROOT, "docs", "schema.sql")
    with open(sql, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(storage.ddl())
    print(f"[docs] wrote {os.path.relpath(path, ROOT)} and {os.path.relpath(sql, ROOT)}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="returnledger", description="ReturnLedger returns workflow toolkit")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp, data=True):
        sp.add_argument("--scale", default="starter", help="starter | full | a number such as 0.25")
        sp.add_argument("--seed", type=int, default=C.DEFAULT_SEED)
        if data:
            sp.add_argument("--data", help="dataset folder (default data/<scale>)")

    sp = sub.add_parser("generate", help="generate and export a dataset")
    common(sp)
    sp.add_argument("--formats", default="csv,json,sql,sqlite")
    sp = sub.add_parser("run", help="generate + validate + audit + report")
    common(sp)
    sp.add_argument("--formats", default="csv,json,sql,sqlite")
    for name in ("validate", "audit", "report"):
        common(sub.add_parser(name))
    common(sub.add_parser("reproduce", help="generate twice and compare checksums"), data=False)
    sp = sub.add_parser("robustness", help="validate + audit across several seeds, clean and with anomalies")
    common(sp, data=False)
    sp.add_argument("--seeds", default="20261022,1,2,3,42")
    sp = sub.add_parser("explain", help="trace one RMA end to end")
    common(sp)
    sp.add_argument("--rma", required=True)
    sp = sub.add_parser("serve", help="open the web UI for a dataset")
    common(sp)
    sp.add_argument("--port", type=int, default=8000)
    sp.add_argument("--no-browser", action="store_true")
    sub.add_parser("docs", help="regenerate docs/DATA_DICTIONARY.md and docs/schema.sql")

    args = p.parse_args(argv)
    handlers = {"generate": lambda a: cmd_generate(a) and 0, "run": cmd_run,
                "validate": lambda a: 0 if cmd_validate(a)[0]["overall_status"] == "PASS" else 1,
                "audit": lambda a: cmd_audit(a) and 0, "report": lambda a: cmd_report(a) and 0,
                "reproduce": cmd_reproduce, "robustness": cmd_robustness, "explain": cmd_explain,
                "serve": cmd_serve, "docs": cmd_docs}
    return handlers[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
