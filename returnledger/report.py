"""Self-contained HTML report (no external assets) plus the generated data dictionary."""
import html

from .schema import TABLES, RELATIONSHIPS, ENUMS, LIFECYCLES

CSS = """
body{font-family:Segoe UI,Arial,sans-serif;margin:0;background:#f5f6f8;color:#1f2933}
header{background:#12355b;color:#fff;padding:24px 32px}header h1{margin:0 0 6px}header p{margin:0;opacity:.85}
main{padding:24px 32px;max-width:1200px}section{background:#fff;border-radius:8px;padding:18px 22px;margin-bottom:18px;
box-shadow:0 1px 3px rgba(0,0,0,.08)}h2{margin-top:0;font-size:18px;color:#12355b}
.cards{display:flex;flex-wrap:wrap;gap:12px}.card{flex:1 1 170px;background:#eef3f9;border-radius:6px;padding:12px}
.card b{display:block;font-size:22px;color:#12355b}.card span{font-size:12px;color:#52606d}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:6px 8px;border-bottom:1px solid #e4e7eb;text-align:left}
th{background:#f0f4f8}td.n{text-align:right;font-variant-numeric:tabular-nums}
.bar{background:#d9e2ec;border-radius:3px;height:10px;position:relative;min-width:120px}
.bar i{position:absolute;left:0;top:0;bottom:0;background:#2f80ed;border-radius:3px}
.PASS{color:#1b7f3b;font-weight:600}.FAIL{color:#c62828;font-weight:600}.PASS_WITH_LABELLED_EXCEPTIONS{color:#b7791f;font-weight:600}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}@media(max-width:900px){.grid{grid-template-columns:1fr}}
small{color:#52606d}
"""


def _e(x):
    return html.escape(str(x))


def _table(headers, rows, numeric=()):
    out = ["<table><tr>" + "".join(f"<th>{_e(h)}</th>" for h in headers) + "</tr>"]
    for r in rows:
        cells = []
        for i, v in enumerate(r):
            cls = ' class="n"' if i in numeric else ""
            cells.append(f"<td{cls}>{v}</td>")
        out.append("<tr>" + "".join(cells) + "</tr>")
    return "".join(out) + "</table>"


def _bar(value, maximum):
    w = 0 if not maximum else max(1, round(100 * value / maximum))
    return f'<div class="bar"><i style="width:{w}%"></i></div>'


def _bars(mapping, label="Count"):
    items = sorted(mapping.items(), key=lambda kv: -kv[1])
    mx = max((v for _, v in items), default=0)
    return _table(["Value", label, ""], [(_e(k), f"{v:,}", _bar(v, mx)) for k, v in items], numeric=(1,))


def render(metrics, validation, evaluation, manifest):
    m, v, ev = metrics, validation, evaluation
    det = ev["anomaly_detection"]
    cards = [
        (f"{m['volume']['sales_orders']:,}", "sales orders"),
        (f"{m['volume']['return_requests']:,}", "return requests (RMAs)"),
        (f"{m['volume']['return_lines']:,}", "return lines"),
        (f"{m['returns']['line_approval_rate_pct']}%", "line approval rate"),
        (f"${m['money']['refunds_paid_usd']:,.2f}", "refunds paid"),
        (f"{m['disposition']['inventory_recovery_rate_pct']}%", "inventory cost recovered"),
        (v["overall_status"], "validation"),
        (f"{det['micro']['precision']:.0%} / {det['micro']['recall']:.0%}", "anomaly precision / recall"),
    ]
    parts = [f"<!doctype html><html><head><meta charset='utf-8'><title>ReturnLedger report</title><style>{CSS}</style>"
             "</head><body><header><h1>ReturnLedger: returns workflow report</h1>"
             f"<p>Seed {manifest['seed']} &middot; scale {manifest['scale']} &middot; as of {manifest['as_of']} "
             f"&middot; generator v{manifest['generator_version']}</p></header><main>"]
    parts.append("<section><h2>Headline</h2><div class='cards'>" + "".join(
        f"<div class='card'><b class='{_e(a)}'>{_e(a)}</b><span>{_e(b)}</span></div>" for a, b in cards) + "</div></section>")

    rows = [(_e(c["category"]), f"{c['units_sold']:,}", f"{c['return_lines']:,}", f"{c['return_rate_pct']}%",
             _bar(c["return_rate_pct"], max(x["return_rate_pct"] for x in m["categories"])), f"{c['approval_rate_pct']}%")
            for c in m["categories"]]
    parts.append("<section><h2>Returns by category</h2>" + _table(
        ["Category", "Units sold", "Return lines", "Unit return rate", "", "Approval rate"], rows, numeric=(1, 2, 3, 5))
        + "<small>Return rate = units requested / units sold. Exclusions (gift cards, groceries, final sale, opened "
          "beauty) drive low approval rates.</small></section>")

    parts.append("<div class='grid'><section><h2>Eligibility decisions (line level)</h2>"
                 + _bars(m["returns"]["decision_reasons"]) + "</section>"
                 "<section><h2>RMA lifecycle status (as of date)</h2>" + _bars(m["pipeline"]["rma_status"]) + "</section></div>")
    parts.append("<div class='grid'><section><h2>Inspection condition</h2>" + _bars(m["inspection_conditions"]) + "</section>"
                 "<section><h2>Disposition (controls inventory movement)</h2>" + _table(
                     ["Disposition", "Units", "Cost value (USD)"],
                     [(k, f"{x['units']:,}", f"{x['cost_value_usd']:,.2f}") for k, x in m["disposition"]["by_disposition"].items()],
                     numeric=(1, 2)) + f"<p>Inventory recovery rate: <b>{m['disposition']['inventory_recovery_rate_pct']}%</b>"
                 " <small>(restock 100%, refurbish 60%, quarantine/scrap 0% of cost)</small></p></section></div>")

    parts.append("<div class='grid'><section><h2>Refund economics</h2>" + _table(
        ["Measure", "Value"], [(_e(k), f"{x:,}") for k, x in m["money"].items()], numeric=(1,)) + "</section>"
        "<section><h2>Cycle times</h2>" + _table(["Measure", "Value"],
                                                 [(_e(k), x) for k, x in m["cycle_times"].items()], numeric=(1,))
        + "</section></div>")

    parts.append("<section><h2>Scenario coverage (normal, boundary, failure, exception)</h2>"
                 + _bars(m["coverage"], "Records") + "</section>")

    rows = [(_e(k), x["ground_truth"], x["detected"], x["tp"], x["fp"], x["fn"], f"{x['precision']:.2%}",
             f"{x['recall']:.2%}") for k, x in det["per_issue_type"].items()]
    fin = ev["financial_impact_usd"]
    parts.append("<section><h2>Exception detection vs ground truth</h2>" + _table(
        ["Issue type", "Ground truth", "Detected", "TP", "FP", "FN", "Precision", "Recall"], rows,
        numeric=(1, 2, 3, 4, 5, 6, 7)) +
        f"<p>Decision conformance on clean lines: <b>{ev['decision_conformance']['clean_match_rate']:.2%}</b> "
        f"({ev['decision_conformance']['clean_lines']:,} lines). Disposition conformance: "
        f"<b>{ev['disposition_conformance']['match_rate']:.2%}</b>. Refund conformance: "
        f"<b>{ev['refund_conformance']['match_rate']:.2%}</b>.</p>"
        f"<p>Leakage from injected anomalies: <b>${fin['leakage_from_injected_anomalies']:,.2f}</b> "
        f"(duplicates ${fin['duplicate_payouts']:,.2f}, over-refunds ${fin['over_refunds']:,.2f}). "
        f"Idempotency blocked {fin['duplicate_attempts_blocked']} retry attempts worth "
        f"${fin['amount_protected_by_idempotency']:,.2f}.</p></section>")

    rows = [(_e(c["category"]), _e(c["check"]), f"{c['rows_checked']:,}", c["violations"], c["labelled"],
             c["unlabelled"], f"<span class='{c['status']}'>{_e(c['status'])}</span>") for c in v["checks"]]
    parts.append("<section><h2>Validation checks</h2>" + _table(
        ["Category", "Check", "Rows", "Violations", "Labelled", "Unlabelled", "Status"], rows, numeric=(2, 3, 4, 5))
        + "</section>")
    parts.append("</main></body></html>")
    return "\n".join(parts)


def data_dictionary_md():
    out = ["# Data dictionary", "",
           "Generated from `returnledger/schema.py` (`python -m returnledger docs`). Money columns are USD with 2 "
           "decimals (stored internally as integer cents); rates are fractions with 4 decimals; timestamps are "
           "ISO-8601 local time without zone; booleans are `true`/`false`; empty = null.", "",
           "## Relationships and cardinality", "", "| Parent | Child | Cardinality | Meaning |", "|---|---|---|---|"]
    out += [f"| {p} | {c} | {card} | {d} |" for p, c, card, d in RELATIONSHIPS]
    out += ["", "## Lifecycles (allowed transitions, recorded in `status_event`)", ""]
    for ent, trans in LIFECYCLES.items():
        out.append(f"- **{ent}**: " + "; ".join(f"{a or '(create)'} -> {'/'.join(sorted(b))}" for a, b in trans.items()))
    out.append("")
    for t in TABLES:
        out += [f"## `{t.name}` ({t.entity})", "", t.desc, "", f"Primary key: `{', '.join(t.pk)}`", "",
                "| Field | Type | Required | Allowed values / format | Unit | Unique | FK | Validation rule | Description |",
                "|---|---|---|---|---|---|---|---|---|"]
        for f in t.fields:
            allowed = ", ".join(ENUMS[f.enum]) if f.enum else (f"`{f.pattern}`" if f.pattern else "")
            out.append(f"| `{f.name}` | {f.type} | {'yes' if f.required else 'no'} | {allowed} | {f.unit} | "
                       f"{'yes' if f.unique or t.pk == [f.name] else ''} | {f.fk or ''} | {f.rule} | {f.desc} |")
        out.append("")
    return "\n".join(out)
