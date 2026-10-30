"use strict";

// ----------------------------------------------------------------- helpers
const cache = {};
async function api(path) {
  if (!cache[path]) {
    cache[path] = fetch(path).then(r => {
      if (!r.ok) throw new Error(`${path}: ${r.status}`);
      return r.json();
    });
  }
  return cache[path];
}
const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const usd = v => v == null ? "" : "$" + Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const num = v => v == null ? "" : Number(v).toLocaleString();
const ts = v => v ? esc(v.replace("T", " ").slice(0, 16)) : "";
const app = () => document.getElementById("app");
const bar = (v, max) => `<div class="bar"><i style="width:${max ? Math.max(1, Math.round(100 * v / max)) : 0}%"></i></div>`;

const STATUS_COLOR = {
  REFUNDED: "b-green", EXCHANGED: "b-green", AUTHORIZED: "b-blue", PARTIALLY_AUTHORIZED: "b-blue", RECEIVED: "b-blue",
  INSPECTED: "b-blue", IN_TRANSIT: "b-blue", SUBMITTED: "b-grey", PENDING: "b-grey", REJECTED: "b-red", EXPIRED: "b-amber",
  LOST_IN_TRANSIT: "b-red", CLOSED_NO_REFUND: "b-amber", APPROVED: "b-green", PARTIALLY_APPROVED: "b-amber",
  PAID: "b-green", BLOCKED_DUPLICATE: "b-amber", REQUESTED: "b-grey", PASS: "b-green", FAIL: "b-red",
  RESTOCK: "b-green", REFURBISH: "b-blue", QUARANTINE: "b-amber", SCRAP: "b-red", LOST: "b-red", LABEL_CREATED: "b-grey",
  HIGH: "b-red", MEDIUM: "b-amber", LOW: "b-grey", PASS_WITH_LABELLED_EXCEPTIONS: "b-amber",
};
const badge = s => `<span class="badge ${STATUS_COLOR[s] || ""}">${esc(String(s).replaceAll("_", " "))}</span>`;

const REASON_TEXT = {
  WITHIN_POLICY: "Within policy: approved as requested",
  QTY_CAPPED: "Asked for more than is still returnable, so approved only the remaining quantity",
  REJECT_LATE: "Requested after the return window (policy window + loyalty extension) with no manager override",
  REJECT_EXCLUDED_CATEGORY: "Category is not returnable for this reason (gift card, or grocery without merchant fault)",
  REJECT_FINAL_SALE: "Clearance / final-sale item and the reason is not merchant fault",
  REJECT_HYGIENE_OPENED: "Opened beauty item (hygiene rule) and the reason is not merchant fault",
  REJECT_QTY_EXCEEDS_PURCHASED: "Everything purchased on this line was already approved on an earlier return",
};
const ISSUE_TEXT = {
  QTY_EXCEEDS_PURCHASED: "Approved quantity is more than the customer bought",
  REFUND_EXCEEDS_PAID: "Refund is more than the customer paid for the item",
  RESTOCK_BEFORE_INSPECTION: "Units were put back on sale before anyone inspected them",
  LATE_APPROVED_WITHOUT_OVERRIDE: "Late return approved without a manager override",
  DUPLICATE_REFUND: "The same return was paid out twice",
};
const CONDITION_TEXT = {
  UNOPENED: "unopened, as new", OPENED_LIKE_NEW: "opened but like new", DAMAGED: "damaged",
  DEFECTIVE: "defective (manufacturer)", NOT_ORIGINAL_ITEM: "not the item we sold (possible fraud)",
};

function setNav(name) {
  document.querySelectorAll("nav a").forEach(a => a.classList.toggle("active", a.dataset.nav === name));
}

// ---------------------------------------------------------------- overview
async function overview() {
  setNav("overview");
  const [s, list] = await Promise.all([api("/api/summary"), api("/api/rmas")]);
  const m = s.metrics, ev = s.evaluation;
  const maxF = s.funnel[0].count;
  const examples = {};
  list.forEach(r => r.issues.forEach(i => { examples[i] = examples[i] || r.rma_id; }));
  const firstWith = pred => (list.find(pred) || {}).rma_id;
  const normal = [
    ["Clean refund", firstWith(r => r.status === "REFUNDED" && !r.issues.length && r.lines > 1)],
    ["Exchange", firstWith(r => r.status === "EXCHANGED" && !r.issues.length)],
    ["Rejected", firstWith(r => r.status === "REJECTED")],
    ["Late but manager override", firstWith(r => r.late && r.decision !== "REJECTED" && !r.issues.length)],
    ["Label expired (missing shipment)", firstWith(r => r.status === "EXPIRED")],
    ["Lost in transit", firstWith(r => r.status === "LOST_IN_TRANSIT")],
  ].filter(x => x[1]);

  app().innerHTML = `
  <div class="card">
    <h1>What is ReturnLedger?</h1>
    <p>When a customer returns something, a store has to answer five questions: <b>Is it eligible?</b> (inside the return
    window, not an excluded item, not more than they bought) <b>Did it arrive?</b> <b>What condition is it in?</b>
    <b>How much do we refund?</b> (what they actually paid after discounts, plus tax, minus fees) and
    <b>What do we do with it?</b> (restock, refurbish, quarantine or scrap).</p>
    <p>ReturnLedger generates a realistic but fully synthetic store history (orders, return requests and every step after),
    applies documented rules to answer those questions, and records every step as its own record with a full event
    history. A few mistakes are planted on purpose (for example, a refund paid twice). An independent audit then has to find
    them, and the result is scored against a separate answer key ("ground truth").</p>
    <div class="chips">
      <span class="chip">Customer: asks to return</span><span class="chip">Store/warehouse operator: receives and inspects</span>
      <span class="chip">Operations manager: overrides, exceptions</span><span class="chip">Analyst: KPIs and leakage</span>
    </div>
  </div>

  <div class="card"><h2>Headline numbers</h2><div class="kpis">
    <div class="kpi"><b>${num(m.volume.sales_orders)}</b><span>sales orders</span></div>
    <div class="kpi"><b>${num(m.volume.return_requests)}</b><span>return requests (RMAs)</span></div>
    <div class="kpi"><b>${num(m.volume.return_lines)}</b><span>return lines (items)</span></div>
    <div class="kpi"><b>${m.returns.line_approval_rate_pct}%</b><span>lines approved</span></div>
    <div class="kpi"><b>${usd(m.money.refunds_paid_usd)}</b><span>refunds paid</span></div>
    <div class="kpi"><b>${m.cycle_times.request_to_refund_days_p50} days</b><span>median request to refund</span></div>
    <div class="kpi"><b>${m.disposition.inventory_recovery_rate_pct}%</b><span>inventory cost recovered</span></div>
    <div class="kpi"><b>${badge(s.validation_status)}</b><span>data validation (${s.validation_totals.passed}/${s.validation_totals.checks} checks)</span></div>
  </div></div>

  <div class="card"><h2>The return journey: how many returns reach each step</h2>
    <div class="funnel">${s.funnel.map(f => `<div class="fstep"><span class="t">${esc(f.stage)}</span><b>${num(f.count)}</b>
      <small>${esc(f.help)}</small><div class="fill" style="width:${Math.round(100 * f.count / maxF)}%"></div></div>`).join("")}</div>
    <div class="grid2" style="margin-top:14px">
      <div><h3>Left the journey early</h3><table>${Object.entries(s.exits).map(([k, v]) =>
        `<tr><td>${esc(k)}</td><td class="n">${num(v)}</td></tr>`).join("")}</table></div>
      <div><h3>How resolved returns ended</h3><table>${Object.entries(s.resolved).map(([k, v]) =>
        `<tr><td>${esc(k)}</td><td class="n">${num(v)}</td></tr>`).join("")}</table></div>
    </div>
  </div>

  <div class="grid2">
    <div class="card"><h2>Try it: open a real example</h2>
      <p class="muted">Each link opens the full trace of one return, from order to refund.</p>
      <h3>Normal and exception paths</h3><div class="chips">${normal.map(([l, id]) =>
        `<a class="chip" href="#/rma/${id}">${esc(l)} &rarr; ${id}</a>`).join("")}</div>
      <h3>Planted mistakes (caught by the audit)</h3><div class="chips">${Object.entries(examples).map(([i, id]) =>
        `<a class="chip" href="#/rma/${id}">${esc(ISSUE_TEXT[i] || i)} &rarr; ${id}</a>`).join("")}</div>
    </div>
    <div class="card"><h2>Did the audit catch the planted mistakes?</h2>
      <table><tr><th>Mistake</th><th class="n">Planted</th><th class="n">Found</th><th class="n">False alarms</th></tr>
      ${Object.entries(ev.anomaly_detection.per_issue_type).map(([k, x]) =>
        `<tr><td>${esc(ISSUE_TEXT[k] || k)}</td><td class="n">${x.ground_truth}</td><td class="n">${x.tp}</td><td class="n">${x.fp}</td></tr>`).join("")}
      </table>
      <p>Money at risk from the planted mistakes: <b>${usd(ev.financial_impact_usd.leakage_from_injected_anomalies)}</b>.
      Separately, the duplicate-payment guard blocked <b>${num(ev.financial_impact_usd.duplicate_attempts_blocked)}</b>
      retry attempts worth <b>${usd(ev.financial_impact_usd.amount_protected_by_idempotency)}</b>.</p>
    </div>
  </div>

  <div class="card"><h2>Returns by product category</h2>
    <table><tr><th>Category</th><th class="n">Units sold</th><th class="n">Return lines</th><th class="n">Return rate</th><th></th><th class="n">Approved</th></tr>
    ${m.categories.map(c => `<tr><td>${esc(c.category)}</td><td class="n">${num(c.units_sold)}</td><td class="n">${num(c.return_lines)}</td>
      <td class="n">${c.return_rate_pct}%</td><td style="width:30%">${bar(c.return_rate_pct, Math.max(...m.categories.map(x => x.return_rate_pct)))}</td>
      <td class="n">${c.approval_rate_pct}%</td></tr>`).join("")}</table>
    <small>Gift cards are never returnable, groceries only when it is our fault, and opened beauty items are refused for
    hygiene, which is why those approval rates are low.</small>
  </div>`;
}

// --------------------------------------------------------------- returns
const listState = { q: "", status: "", issue: "", page: 0 };
async function returns() {
  setNav("returns");
  const list = await api("/api/rmas");
  const statuses = [...new Set(list.map(r => r.status))].sort();
  const issues = [...new Set(list.flatMap(r => r.issues))].sort();
  app().innerHTML = `<div class="card"><h2>Returns explorer</h2>
    <div class="explain">Every row is one return request (RMA). Click a row to see the whole story: the decision for each item,
    the parcel, the inspection, the refund maths and every status change.</div>
    <div class="filters">
      <input type="search" id="q" placeholder="Search RMA, order or category..." value="${esc(listState.q)}">
      <select id="status"><option value="">All statuses</option>${statuses.map(s => `<option ${s === listState.status ? "selected" : ""}>${s}</option>`).join("")}</select>
      <select id="issue"><option value="">All returns</option><option value="__any" ${listState.issue === "__any" ? "selected" : ""}>Flagged by audit</option>
        ${issues.map(s => `<option value="${s}" ${s === listState.issue ? "selected" : ""}>${esc(ISSUE_TEXT[s] || s)}</option>`).join("")}</select>
      <span id="count" class="muted"></span>
    </div>
    <div id="table"></div></div>`;
  const draw = () => {
    const q = listState.q.trim().toUpperCase();
    const rows = list.filter(r => (!q || r.rma_id.includes(q) || r.order_id.includes(q) || r.categories.join(" ").includes(q))
      && (!listState.status || r.status === listState.status)
      && (!listState.issue || (listState.issue === "__any" ? r.issues.length : r.issues.includes(listState.issue))));
    const per = 50, pages = Math.max(1, Math.ceil(rows.length / per));
    listState.page = Math.min(listState.page, pages - 1);
    const slice = rows.slice(listState.page * per, listState.page * per + per);
    document.getElementById("count").textContent = `${num(rows.length)} returns`;
    document.getElementById("table").innerHTML = `<table class="list"><tr><th>RMA</th><th>Requested</th><th>Order</th><th>Items</th><th>Categories</th>
      <th>Wants</th><th>Decision</th><th>Status</th><th class="n">Paid</th><th>Audit</th></tr>
      ${slice.map(r => `<tr class="click" data-id="${r.rma_id}"><td><a href="#/rma/${r.rma_id}">${r.rma_id}</a></td><td>${ts(r.requested_at)}</td>
        <td>${r.order_id}</td><td class="n">${r.lines}</td><td class="wrap">${esc(r.categories.join(", "))}</td><td>${esc(r.resolution)}</td>
        <td>${badge(r.decision)}</td><td>${badge(r.status)}</td><td class="n">${r.paid ? usd(r.paid) : ""}</td>
        <td>${r.issues.map(i => `<span class="badge b-red" title="${esc(ISSUE_TEXT[i])}">${esc(i.replaceAll("_", " "))}</span>`).join(" ")}</td></tr>`).join("")}
      </table><div class="pager"><button id="prev" ${listState.page ? "" : "disabled"}>&larr; Prev</button>
      <span>Page ${listState.page + 1} / ${pages}</span><button id="next" ${listState.page < pages - 1 ? "" : "disabled"}>Next &rarr;</button></div>`;
    document.querySelectorAll("tr.click").forEach(tr => tr.onclick = () => location.hash = `#/rma/${tr.dataset.id}`);
    document.getElementById("prev").onclick = () => { listState.page--; draw(); };
    document.getElementById("next").onclick = () => { listState.page++; draw(); };
  };
  document.getElementById("q").oninput = e => { listState.q = e.target.value; listState.page = 0; draw(); };
  document.getElementById("status").onchange = e => { listState.status = e.target.value; listState.page = 0; draw(); };
  document.getElementById("issue").onchange = e => { listState.issue = e.target.value; listState.page = 0; draw(); };
  draw();
}

// ------------------------------------------------------------- RMA detail
function story(d) {
  const r = d.rma, c = d.customer, lines = d.lines;
  const days = lines[0] && lines[0].decision ? lines[0].decision.days_since_delivery : null;
  const approved = lines.filter(l => l.decision && l.decision.approved_qty > 0).length;
  const wants = { REFUND: "get a refund for", EXCHANGE: "exchange", STORE_CREDIT: "get store credit for" }[r.resolution_type];
  let s = `Customer <b>${esc(c.customer_id)}</b> (${esc(c.loyalty_tier)} tier) asked to <b>${esc(wants)}</b>
    ${lines.length} item${lines.length > 1 ? "s" : ""} from order <b>${esc(d.order.order_id)}</b>`;
  if (days != null) s += `, ${days} day${days === 1 ? "" : "s"} after delivery`;
  s += ". ";
  if (!d.authorization) s += "The request is still waiting for a decision.";
  else s += `The rules approved ${approved} of ${lines.length} item${lines.length > 1 ? "s" : ""} (${badge(d.authorization.decision_status)}). `;
  const paid = d.refunds.filter(x => x.current_status === "PAID");
  if (paid.length) s += `Refunded <b>${usd(paid[0].paid_amount)}</b>${paid.length > 1 ? ` <span class="warn">and then paid again (${paid.length} payouts)</span>` : ""}. `;
  if (d.exchange_order) s += `A replacement was sent on exchange order <b>${esc(d.exchange_order.order_id)}</b>. `;
  const map = { EXPIRED: "The customer never shipped the parcel and the label expired.", LOST_IN_TRANSIT: "The carrier lost the parcel.",
    CLOSED_NO_REFUND: "After inspection nothing was refundable.", REJECTED: "Nothing was eligible, so the request was closed." };
  if (map[r.current_status]) s += map[r.current_status];
  return s;
}

function stepper(d) {
  const ev = {};
  d.events.filter(e => e.entity_type === "RETURN_REQUEST").forEach(e => { ev[e.to_status] = e.event_ts; });
  const dec = ["AUTHORIZED", "PARTIALLY_AUTHORIZED", "REJECTED"].find(k => ev[k]);
  const end = ["REFUNDED", "EXCHANGED", "CLOSED_NO_REFUND"].find(k => ev[k]);
  const stop = ["REJECTED", "EXPIRED", "LOST_IN_TRANSIT"].find(k => ev[k]);
  const steps = [
    ["Requested", ev.SUBMITTED, "done"],
    ["Decided", dec ? ev[dec] : null, dec === "REJECTED" ? "bad" : dec ? "done" : "open"],
    ["Shipped", ev.IN_TRANSIT || ev.EXPIRED, ev.EXPIRED ? "bad" : ev.IN_TRANSIT ? "done" : ""],
    ["Received", ev.RECEIVED || ev.LOST_IN_TRANSIT, ev.LOST_IN_TRANSIT ? "bad" : ev.RECEIVED ? "done" : ""],
    ["Inspected", ev.INSPECTED, ev.INSPECTED ? "done" : ""],
    [end ? end.replaceAll("_", " ").toLowerCase().replace(/^./, c => c.toUpperCase()) : "Resolved", end ? ev[end] : null, end ? "done" : ""],
  ];
  let reachedStop = false;
  return `<div class="stepper">${steps.map(([l, t, cls]) => {
    if (reachedStop) cls = "";
    if (cls === "bad") reachedStop = true;
    const label = cls === "bad" && stop ? stop.replaceAll("_", " ").toLowerCase() : l;
    return `<div class="step ${cls}"><span class="dot"></span><div class="lbl">${esc(label)}</div><div class="ts">${ts(t) || "&nbsp;"}</div></div>`;
  }).join("")}</div>`;
}

async function rmaDetail(id) {
  setNav("returns");
  let d;
  try { d = await api(`/api/rma/${id}`); } catch (e) { app().innerHTML = `<div class="card">RMA ${esc(id)} not found.</div>`; return; }
  const r = d.rma;
  const inspAt = {};
  d.lines.forEach(l => l.inspections.forEach(i => { inspAt[i.inspection_id] = i.inspected_at; }));
  const lineName = {};
  d.lines.forEach(l => { lineName[l.return_line_id] = `${l.product_name} (${l.order_line.category})`; });

  const findings = d.findings.map(f => `<div class="alert red"><b>Audit flag [${esc(f.severity)}]: ${esc(ISSUE_TEXT[f.issue_type] || f.issue_type)}</b>
    ${esc(f.detail)} on <code>${esc(f.entity_id)}</code><br><small>Recommended action: ${esc(f.recommended_action)}</small></div>`).join("");
  const gt = d.ground_truth.map(a => `<div class="alert grey"><b>Answer key (ground truth, used only to score the audit): planted ${esc(a.issue_type)}</b>
    ${esc(a.description)}. Expected <code>${esc(a.expected_value)}</code>, recorded <code>${esc(a.recorded_value)}</code>.</div>`).join("");
  const clean = !d.findings.length && !d.ground_truth.length
    ? `<div class="alert green"><b>No exceptions</b>Every step of this return follows the rules.</div>` : "";

  const decisions = d.lines.map(l => {
    const a = l.decision, o = l.order_line;
    const flags = [o.is_final_sale && "final sale", l.item_opened && "opened", a && a.override_applied && "manager override"].filter(Boolean);
    return `<tr><td><b>${esc(l.product_name)}</b><br><small>${esc(l.return_line_id)} &middot; ${esc(o.category)}</small></td>
      <td class="n">${o.qty}</td><td class="n">${l.requested_qty}</td><td class="n">${a ? a.approved_qty : ""}</td>
      <td>${a ? badge(a.line_decision) : badge("PENDING")}</td>
      <td>${a ? esc(REASON_TEXT[a.decision_reason] || a.decision_reason) : "Waiting for decision"}
        ${a ? `<br><small>${a.days_since_delivery} days since delivery / window ${a.effective_window_days} days &middot; ${esc(a.policy_id)}</small>` : ""}</td>
      <td>${esc(l.return_reason.replaceAll("_", " ").toLowerCase())}${flags.length ? `<br><small>${esc(flags.join(", "))}</small>` : ""}</td>
      <td class="n">${usd(o.line_total)}<br><small>${usd(o.unit_price)} x ${o.qty}${o.line_discount ? `, -${usd(o.line_discount)} promo` : ""}${o.allocated_order_discount ? `, -${usd(o.allocated_order_discount)} coupon` : ""}${o.tax_amount ? `, +${usd(o.tax_amount)} tax` : ""}</small></td></tr>`;
  }).join("");

  const ships = d.shipments.length ? `<table><tr><th>Shipment</th><th>Carrier</th><th>Status</th><th>Label</th><th>Shipped</th><th>Received</th><th>Items</th></tr>
    ${d.shipments.map(s => `<tr><td>${esc(s.shipment_id)}<br><small>${esc(s.tracking_number)}</small></td><td>${esc(s.carrier)}</td><td>${badge(s.current_status)}</td>
      <td>${ts(s.label_created_at)}</td><td>${ts(s.shipped_at)}</td><td>${ts(s.received_at)}</td>
      <td>${s.lines.map(x => `${esc(lineName[x.return_line_id])} x${x.shipped_qty}`).join("<br>")}</td></tr>`).join("")}</table>`
    : `<p class="muted">No return label: nothing was approved, or the decision is still pending.</p>`;

  const insp = d.lines.flatMap(l => l.inspections.map(i => ({ l, i })));
  const inspections = insp.length ? `<table><tr><th>Item</th><th class="n">Received</th><th>Condition</th><th>Result</th><th>Inspected</th><th>Disposition</th><th>Stock moved to</th><th>Decided</th></tr>
    ${insp.map(({ l, i }) => {
      const dsp = i.disposition, early = dsp && dsp.decided_at < i.inspected_at;
      return `<tr><td>${esc(l.product_name)}<br><small>${esc(i.inspection_id)}</small></td><td class="n">${i.received_qty}</td>
        <td>${esc(CONDITION_TEXT[i.condition_grade] || i.condition_grade)}${i.damage_attribution !== "NONE" ? `<br><small>caused by ${esc(i.damage_attribution.toLowerCase())}</small>` : ""}</td>
        <td>${badge(i.inspection_result)}</td><td>${ts(i.inspected_at)}</td><td>${dsp ? badge(dsp.disposition) : ""}</td>
        <td>${i.movement ? `${esc(i.movement.to_location)}<br><small>${i.movement.qty} x ${usd(i.movement.unit_cost)} cost</small>` : ""}</td>
        <td class="${early ? "warn" : ""}">${dsp ? ts(dsp.decided_at) : ""}${early ? "<br>before inspection!" : ""}</td></tr>`;
    }).join("")}</table>` : `<p class="muted">Nothing has been inspected yet.</p>`;

  const refunds = d.refunds.length ? d.refunds.map(x => `
    <h3>${esc(x.refund_id)} ${badge(x.current_status)} <small>key ${esc(x.idempotency_key)} &middot; ${esc(x.refund_method.replaceAll("_", " ").toLowerCase())} &middot; requested ${ts(x.requested_at)}</small></h3>
    ${x.blocked_reason ? `<p class="muted">Blocked: ${esc(x.blocked_reason)}. Nothing paid; this is the duplicate-payment guard working.</p>` : ""}
    <table><tr><th>Item</th><th class="n">Qty</th><th class="n">Paid price share</th><th class="n">Tax</th><th class="n">Restocking fee</th>
      <th class="n">Damage deduction</th><th class="n">Cap</th><th class="n">Line refund</th></tr>
      ${x.lines.map(y => `<tr><td>${esc(lineName[y.return_line_id])}</td><td class="n">${y.refund_qty}</td><td class="n">${usd(y.merchandise_amount)}</td>
        <td class="n">${usd(y.tax_amount)}</td><td class="n">-${usd(y.restocking_fee)}</td><td class="n">-${usd(y.damage_deduction)}</td>
        <td class="n">-${usd(y.cap_adjustment)}</td><td class="n">${usd(y.line_refund_amount)}</td></tr>`).join("")}
      <tr><td colspan="7">+ original shipping refunded</td><td class="n">${usd(x.shipping_refund)}</td></tr>
      <tr><td colspan="7">- return label fee</td><td class="n">-${usd(x.return_label_fee)}</td></tr>
      <tr class="total"><td colspan="7">Refund amount (paid ${usd(x.paid_amount)})</td><td class="n">${usd(x.refund_amount)}</td></tr></table>`).join("")
    : d.exchange_order ? `<p>No money refunded: exchanged for order <b>${esc(d.exchange_order.order_id)}</b> (${badge(d.exchange_order.current_status)}, $0.00).</p>`
      : `<p class="muted">No refund.</p>`;

  const events = `<ul class="timeline">${d.events.map(e => `<li><span class="ts">${ts(e.event_ts)}</span><span>${esc(e.entity_type.replaceAll("_", " ").toLowerCase())}</span>
    <span>${esc(e.entity_id)}: ${esc(e.from_status || "created")} &rarr; <b>${esc(e.to_status)}</b></span><span class="muted">${esc(e.actor_role)}</span></li>`).join("")}</ul>`;

  app().innerHTML = `
    <p><a href="#/returns">&larr; Back to returns</a></p>
    <div class="card"><h1>${esc(r.rma_id)} ${badge(r.current_status)}</h1>
      <p>${story(d)}</p>${stepper(d)}</div>
    ${findings}${gt}${clean}
    <div class="card"><h2>1. Eligibility: what was asked and what the rules decided</h2>
      <table><tr><th>Item</th><th class="n">Bought</th><th class="n">Asked</th><th class="n">Approved</th><th>Decision</th><th>Why</th><th>Customer reason</th><th class="n">Customer paid</th></tr>${decisions}</table>
      ${r.late_override_flag ? `<p><b>Manager override</b> by ${esc(r.override_by)} (${esc(r.override_reason)}) allows a late return.</p>` : ""}</div>
    <div class="card"><h2>2. Return shipment</h2>${ships}</div>
    <div class="card"><h2>3. Inspection and disposition (decides what happens to the stock)</h2>${inspections}</div>
    <div class="card"><h2>4. Refund calculation</h2>
      <div class="explain">Refund = share of what the customer actually paid (after promotions and coupon) + matching tax
      - restocking fee (opened, not our fault) - damage deduction (customer damage) - cap (never more than paid)
      + shipping (if our fault) - label fee (customer reason, mailed back).</div>${refunds}</div>
    <div class="card"><h2>5. Event history (append-only, never overwritten)</h2>${events}</div>`;
}

// ------------------------------------------------------------- exceptions
async function exceptions() {
  setNav("exceptions");
  const d = await api("/api/exceptions");
  const per = d.evaluation.anomaly_detection.per_issue_type, fin = d.evaluation.financial_impact_usd;
  const render = filter => {
    const rows = d.findings.filter(f => !filter || f.issue_type === filter);
    document.getElementById("rows").innerHTML = `<table><tr><th>Severity</th><th>Issue</th><th>Record</th><th>RMA</th><th>Detail</th><th>Recommended action</th></tr>
      ${rows.map(f => `<tr class="click" data-id="${f.rma_id}"><td>${badge(f.severity)}</td><td>${esc(ISSUE_TEXT[f.issue_type] || f.issue_type)}</td>
        <td>${esc(f.entity_id)}</td><td><a href="#/rma/${f.rma_id}">${esc(f.rma_id)}</a></td><td>${esc(f.detail)}</td><td>${esc(f.recommended_action)}</td></tr>`).join("")}</table>`;
    document.querySelectorAll("tr.click").forEach(tr => tr.onclick = () => location.hash = `#/rma/${tr.dataset.id}`);
  };
  app().innerHTML = `<div class="card"><h2>Exceptions found by the audit</h2>
    <div class="explain">The audit reads only the exported data, recomputes what the rules say should have happened, and flags every
    difference. Its findings are compared with the answer key of planted mistakes: <b>found</b> = correctly flagged,
    <b>false alarm</b> = flagged but not planted, <b>missed</b> = planted but not flagged.</div>
    <div class="grid3">${Object.entries(per).map(([k, x]) => `<div class="kpi"><b>${x.tp} / ${x.ground_truth}</b>
      <span>${esc(ISSUE_TEXT[k] || k)}<br>false alarms ${x.fp} &middot; missed ${x.fn}</span></div>`).join("")}
      <div class="kpi"><b>${usd(fin.leakage_from_injected_anomalies)}</b><span>money at risk from planted mistakes</span></div></div></div>
    <div class="card"><div class="filters"><select id="f"><option value="">All issue types (${d.findings.length})</option>
      ${Object.keys(per).map(k => `<option value="${k}">${esc(ISSUE_TEXT[k] || k)}</option>`).join("")}</select></div><div id="rows"></div></div>`;
  document.getElementById("f").onchange = e => render(e.target.value);
  render("");
}

// ------------------------------------------------------------------ rules
async function rules() {
  setNav("rules");
  const d = await api("/api/rules");
  app().innerHTML = `
  <div class="card"><h2>Return policy by category (effective-dated)</h2>
    <div class="explain">The policy in force on the <b>order date</b> applies. Apparel changed from 60 to 45 days on 1 July 2026.
    Loyalty adds days: GOLD +15, PLATINUM +30.</div>
    <table><tr><th>Policy</th><th>Category</th><th>Effective</th><th class="n">Window (days)</th><th>Returnable</th><th>Opened OK</th><th class="n">Restocking fee</th><th>Merchant-fault exception</th></tr>
    ${d.policies.map(p => `<tr><td>${esc(p.policy_id)}</td><td>${esc(p.category)}</td><td>${esc(p.effective_from)} &rarr; ${esc(p.effective_to || "open")}</td>
      <td class="n">${p.return_window_days}</td><td>${p.returnable ? "yes" : badge("NO")}</td><td>${p.opened_returnable ? "yes" : "no"}</td>
      <td class="n">${Math.round(p.restocking_fee_rate * 100)}%</td><td>${p.merchant_fault_override ? "yes" : "no"}</td></tr>`).join("")}</table></div>
  <div class="grid2">
    <div class="card"><h2>Eligibility: checked in this order</h2><ol>
      <li><b>Category exclusion</b>: gift cards never; groceries only if defective, damaged in transit or wrong item.</li>
      <li><b>Final sale</b> (clearance): only if it was our fault.</li>
      <li><b>Hygiene</b>: opened beauty items only if it was our fault.</li>
      <li><b>Return window</b>: days since delivery &le; window + loyalty extension. The last day counts. Late needs a manager override.</li>
      <li><b>Quantity</b>: approve up to what was bought minus what earlier returns already approved.</li></ol>
      <small>Exclusions come before the window, so a manager override can waive lateness but never an exclusion.</small></div>
    <div class="card"><h2>Refund formula</h2><div class="formula">paid share   = net paid for line x returned / bought
tax          = line tax x returned / bought
restocking   = paid share x fee%      (opened, not our fault)
damage       = 50% of paid share      (customer damage)
cap          = whatever would exceed what was paid
line refund  = paid share + tax - restocking - damage - cap
refund       = sum(lines) + shipping (our fault) - $6.99 label
               (label fee only for refunds to card, customer reason, mailed)</div>
      <p><small>A not-original item gets $0. Each return has one payment key, and a retry with the same key is blocked.</small></p></div>
  </div>
  <div class="card"><h2>Disposition matrix (controls where stock goes)</h2>
    <table><tr><th>Condition</th><th>Decision</th><th>Stock moves to</th></tr>
      <tr><td>Unopened</td><td>${badge("RESTOCK")} (grocery ${badge("SCRAP")})</td><td>SELLABLE</td></tr>
      <tr><td>Opened, like new</td><td>Electronics ${badge("REFURBISH")}; beauty/grocery ${badge("SCRAP")}; others ${badge("RESTOCK")}</td><td>REFURB_BENCH / SCRAP_BIN / SELLABLE</td></tr>
      <tr><td>Damaged</td><td>Electronics or &ge; $100 ${badge("REFURBISH")}; otherwise ${badge("SCRAP")}</td><td>REFURB_BENCH / SCRAP_BIN</td></tr>
      <tr><td>Defective</td><td>Electronics, toys, home ${badge("QUARANTINE")} (vendor/safety); otherwise ${badge("SCRAP")}</td><td>QUARANTINE_CAGE / SCRAP_BIN</td></tr>
      <tr><td>Not the original item</td><td>${badge("QUARANTINE")} (fraud review)</td><td>QUARANTINE_CAGE</td></tr></table>
    <small>Stock may only move after inspection. A move before inspection is flagged as an exception.</small></div>`;
}

// ---------------------------------------------------------------- quality
async function quality() {
  setNav("quality");
  const d = await api("/api/quality");
  const v = d.validation, rep = d.reproducibility, rob = d.robustness;
  app().innerHTML = `
  <div class="card"><h2>Data validation ${badge(v.overall_status)}</h2>
    <div class="explain">Every check runs on the exported files. A violation is <b>labelled</b> when it is one of the planted mistakes in the
    answer key. A check fails only if it finds something that is <b>not</b> planted, which proves the rest of the data is clean.</div>
    <table><tr><th>Area</th><th>Check</th><th class="n">Rows checked</th><th class="n">Violations</th><th class="n">Planted</th><th class="n">Unexplained</th><th>Status</th></tr>
    ${v.checks.map(c => `<tr><td>${esc(c.category)}</td><td>${esc(c.check)}<br><small>${esc(c.rule)}</small></td><td class="n">${num(c.rows_checked)}</td>
      <td class="n">${c.violations}</td><td class="n">${c.labelled}</td><td class="n">${c.unlabelled}</td><td>${badge(c.status)}</td></tr>`).join("")}</table></div>
  <div class="grid2">
    <div class="card"><h2>Reproducibility ${rep ? badge(rep.all_identical ? "PASS" : "FAIL") : ""}</h2>
      ${rep ? `<p>Generated twice with seed <b>${rep.seed}</b>: <b>${rep.files.filter(f => f.identical).length} / ${rep.files_compared}</b> files byte-identical (SHA-256).</p>
      <table><tr><th>File</th><th class="n">Rows</th><th>SHA-256</th></tr>${rep.files.slice(0, 40).map(f => `<tr><td>${esc(f.file)}</td>
        <td class="n">${num(f.rows_run_a)}</td><td><code>${esc(f.sha256_run_a.slice(0, 16))}</code></td></tr>`).join("")}</table>`
      : `<p class="muted">Run <code>python -m returnledger reproduce</code> to create this report.</p>`}</div>
    <div class="card"><h2>Robustness across seeds ${rob ? badge(rob.all_passed ? "PASS" : "FAIL") : ""}</h2>
      ${rob ? `<table><tr><th>Seed</th><th>Mistakes planted?</th><th>Validation</th><th class="n">Unexplained</th><th class="n">Found / planted</th></tr>
        ${rob.runs.map(x => `<tr><td>${x.seed}</td><td>${x.anomalies ? "yes" : "no (clean)"}</td><td>${badge(x.validation)}</td>
          <td class="n">${x.unlabelled}</td><td class="n">${x.tp} / ${x.ground_truth}</td></tr>`).join("")}</table>`
      : `<p class="muted">Run <code>python -m returnledger robustness</code> to create this report.</p>`}
      <h3>Provenance</h3><p>${esc(d.manifest.provenance.statement)}</p></div>
  </div>`;
}

// ----------------------------------------------------------------- router
async function route() {
  const h = location.hash || "#/overview";
  try {
    if (h.startsWith("#/rma/")) await rmaDetail(decodeURIComponent(h.slice(6)));
    else if (h === "#/returns") await returns();
    else if (h === "#/exceptions") await exceptions();
    else if (h === "#/rules") await rules();
    else if (h === "#/quality") await quality();
    else await overview();
  } catch (e) {
    app().innerHTML = `<div class="card"><b>Could not load data.</b><p>${esc(e.message)}</p>
      <p>Generate the dataset first: <code>python -m returnledger run --scale starter</code></p></div>`;
  }
  window.scrollTo(0, 0);
}
window.addEventListener("hashchange", route);
api("/api/summary").then(s => {
  document.getElementById("dataset-label").textContent =
    `seed ${s.manifest.seed} · scale ${s.manifest.scale} · as of ${s.manifest.as_of.slice(0, 10)}`;
}).catch(() => {});
route();
