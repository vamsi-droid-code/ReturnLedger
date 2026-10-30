"""Deterministic synthetic data generator.

Pipeline (each stage uses its own seeded RNG stream so stages are independent):
  1. reference/master data   : return_policy, customer, product
  2. sales transactions      : orders, order_line (+ ORDER status events)
  3. return demand           : return_request, return_line (inputs only, no decisions)
  4. policy decisions        : return_authorization, authorization_line (policy engine)
  5. decision anomalies      : labelled injections into recorded decisions (anomalies.py)
  6. downstream lifecycle    : shipments, inspections, refunds, dispositions, movements,
                               exchange orders, status events
  7. post-process anomalies  : labelled injections into refunds / dispositions
  8. finalize                : event ids, current_status derived from the event history
All derived values (totals, statuses, refund amounts) are computed from source records.
"""
import math
import random
from datetime import datetime, timedelta, date, time

from . import config as C
from . import policy as P
from .money import apply_rate, half_up_div
from .schema import TABLES

FIRST_NAMES = [
    "James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael", "Linda", "David", "Elizabeth",
    "William", "Barbara", "Richard", "Susan", "Joseph", "Jessica", "Thomas", "Sarah", "Charles", "Karen",
    "Priya", "Arjun", "Wei", "Mei", "Carlos", "Sofia", "Ahmed", "Fatima", "Kenji", "Yuki",
    "Liam", "Olivia", "Noah", "Emma", "Mateo", "Ava", "Ravi", "Ananya", "Diego", "Lucia",
]
LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez",
    "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Patel", "Kim", "Nguyen", "Chen", "Singh", "Kumar", "Shah", "Wang", "Tanaka",
    "Clark", "Lewis", "Walker", "Hall", "Allen", "Young", "King", "Wright", "Scott", "Green",
]
BRANDS = ["Acme", "Northwind", "Contoso", "Fabrikam", "Lumen", "Orbit", "Vertex", "Harbor", "Summit", "Willow"]
NOUNS = {
    "APPAREL": ["T-Shirt", "Jeans", "Hoodie", "Jacket", "Dress", "Sneakers", "Sweater", "Shorts"],
    "ELECTRONICS": ["Headphones", "Smartwatch", "Tablet", "Bluetooth Speaker", "Monitor", "Keyboard", "Camera"],
    "HOME": ["Lamp", "Blender", "Cookware Set", "Throw Blanket", "Vacuum", "Coffee Maker", "Rug"],
    "BEAUTY": ["Face Serum", "Lipstick", "Shampoo", "Perfume", "Moisturizer", "Hair Dryer Kit"],
    "GROCERY": ["Coffee Beans", "Olive Oil", "Protein Bars", "Green Tea", "Pasta Pack", "Snack Box"],
    "TOYS": ["Building Blocks", "Puzzle", "Plush Toy", "RC Car", "Board Game", "Doll House"],
    "SPORTS": ["Yoga Mat", "Dumbbells", "Running Shoes", "Tennis Racket", "Bike Helmet", "Water Bottle"],
    "BOOKS": ["Novel", "Cookbook", "Biography", "Travel Guide", "Textbook", "Comic Volume"],
    "JEWELRY": ["Necklace", "Bracelet", "Earrings", "Ring", "Watch"],
    "GIFT_CARD": ["Gift Card"],
}
ADJECTIVES = ["Classic", "Pro", "Lite", "Deluxe", "Eco", "Essential", "Premium", "Compact", "Signature", "Urban"]

REASON_WEIGHTS_FIT = {"WRONG_SIZE": 45, "CHANGED_MIND": 25, "NOT_AS_DESCRIBED": 15,
                      "DEFECTIVE": 5, "DAMAGED_IN_TRANSIT": 5, "WRONG_ITEM": 5}
REASON_WEIGHTS_OTHER = {"CHANGED_MIND": 35, "NOT_AS_DESCRIBED": 20, "DEFECTIVE": 20,
                        "DAMAGED_IN_TRANSIT": 12, "WRONG_ITEM": 8, "WRONG_SIZE": 5}
OPENED_PROB = {"CHANGED_MIND": 0.35, "WRONG_SIZE": 0.30, "NOT_AS_DESCRIBED": 0.60,
               "DEFECTIVE": 0.90, "DAMAGED_IN_TRANSIT": 0.50, "WRONG_ITEM": 0.10}
TRACKING_PREFIX = {"UPS": "1Z", "FEDEX": "FX", "USPS": "94", "DHL": "JD", "STORE_DROPOFF": "ST"}

SECOND_RMA_SHARE = 0.045
LATE_SHARE = 0.10
OVERRIDE_SHARE = 0.30
MISSING_SHIPMENT_SHARE = 0.03
LOST_SHARE = 0.015
SPLIT_SHARE = 0.12
SHORTAGE_SHARE = 0.03
BLOCKED_RETRY_SHARE = 0.04


def wchoice(rng, mapping):
    keys = list(mapping)
    return rng.choices(keys, weights=[mapping[k] for k in keys])[0]


def weighted_sample(rng, items, weights, k):
    """Weighted sampling without replacement (Efraimidis-Spirakis), deterministic."""
    keyed = [(rng.random() ** (1.0 / w), i) for i, w in enumerate(weights) if w > 0]
    keyed.sort(reverse=True)
    return [items[i] for _, i in keyed[:k]]


def minutes(rng, lo, hi):
    return timedelta(minutes=rng.randint(lo, hi))


class Generator:
    def __init__(self, seed=C.DEFAULT_SEED, scale=1.0):
        self.seed = seed
        self.scale = scale
        v = C.FULL_VOLUME
        self.n_customers = max(50, round(v["customers"] * scale))
        self.n_orders = max(100, round(v["orders"] * scale))
        self.n_requests = max(20, round(v["return_requests"] * scale))
        self.n_lines = max(self.n_requests, round(v["return_lines"] * scale))
        self.anomaly_counts = {k: max(C.ANOMALY_MIN, round(n * scale)) for k, n in C.ANOMALY_COUNTS_FULL.items()}
        self.t = {tab.name: [] for tab in TABLES}
        self.events = []
        self.counters = {}
        self.gt_anomalies = []
        self.gt_labels = {}
        self.policies = P.build_policies()

    # ------------------------------------------------------------------ utilities
    def rng(self, stage):
        return random.Random(f"{self.seed}:{stage}")

    def next_id(self, prefix, width=6, year=True):
        n = self.counters.get(prefix, 0) + 1
        self.counters[prefix] = n
        return f"{prefix}-2026-{n:0{width}d}" if year else f"{prefix}-{n:0{width}d}"

    def event(self, entity_type, entity_id, frm, to, ts, actor_role, actor_id=None, reason=None):
        self.events.append({
            "entity_type": entity_type, "entity_id": entity_id, "from_status": frm, "to_status": to,
            "event_ts": ts, "actor_role": actor_role, "actor_id": actor_id, "reason_code": reason,
            "_seq": len(self.events),
        })

    # ------------------------------------------------------------------- pipeline
    def run(self):
        from . import anomalies
        self.gen_policies()
        self.gen_customers()
        self.gen_products()
        self.gen_orders()
        self.gen_return_requests()
        self.gen_authorizations()
        anomalies.inject_decision_anomalies(self)
        self.gen_downstream()
        self.record_expected_outcomes()
        anomalies.inject_post_anomalies(self)
        self.finalize()
        return self

    # ------------------------------------------------------------ 1. master data
    def gen_policies(self):
        for p in self.policies:
            self.t["return_policy"].append({
                "policy_id": p.policy_id, "category": p.category, "version": p.version,
                "effective_from": p.effective_from, "effective_to": p.effective_to,
                "return_window_days": p.return_window_days, "returnable": p.returnable,
                "opened_returnable": p.opened_returnable, "restocking_fee_rate": p.restocking_fee_rate,
                "merchant_fault_override": p.merchant_fault_override,
            })

    def gen_customers(self):
        rng = self.rng("customers")
        start, span = date(2021, 1, 1), (date(2025, 12, 31) - date(2021, 1, 1)).days
        self.customers = {}
        weights = []
        for i in range(1, self.n_customers + 1):
            cid = f"CUST-{i:06d}"
            row = {
                "customer_id": cid,
                "customer_name": f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}",
                "email": f"user{i:06d}@example.com",
                "loyalty_tier": wchoice(rng, C.LOYALTY_TIERS),
                "home_state": wchoice(rng, C.STATE_WEIGHTS),
                "signup_date": start + timedelta(days=rng.randrange(span)),
                "customer_status": "ACTIVE" if rng.random() > 0.01 else "CLOSED",
            }
            self.t["customer"].append(row)
            self.customers[cid] = row
            weights.append(min(rng.paretovariate(1.6), 25.0))
        self.customer_ids = list(self.customers)
        self.customer_cum = []
        acc = 0.0
        for w in weights:
            acc += w
            self.customer_cum.append(acc)

    def gen_products(self):
        rng = self.rng("products")
        total_w = sum(C.CATEGORY_WEIGHTS.values())
        protos = []
        for cat in C.CATEGORIES:
            n = max(5, round(C.PRODUCT_COUNT * C.CATEGORY_WEIGHTS[cat] / total_w))
            lo, hi, clo, chi = C.PRICE_RANGES[cat]
            for _ in range(n):
                if cat == "GIFT_CARD":
                    price = rng.choice([2500, 5000, 10000, 20000])
                    cost = price
                    name = f"{rng.choice(BRANDS)} Gift Card ${price // 100}"
                else:
                    raw = math.exp(rng.uniform(math.log(lo), math.log(hi)))
                    price = max(lo, int(raw) // 100 * 100 + 99)
                    cost = max(1, round(price * rng.uniform(clo, chi)))
                    name = f"{rng.choice(BRANDS)} {rng.choice(ADJECTIVES)} {rng.choice(NOUNS[cat])}"
                protos.append((cat, name, price, cost))
        rng.shuffle(protos)
        self.products = {}
        self.products_by_cat = {c: [] for c in C.CATEGORIES}
        for i, (cat, name, price, cost) in enumerate(protos, 1):
            sku = f"SKU-{i:06d}"
            row = {"sku": sku, "product_name": name, "category": cat, "list_price": price, "unit_cost": cost}
            self.t["product"].append(row)
            self.products[sku] = row
            self.products_by_cat[cat].append(sku)

    # ---------------------------------------------------------------- 2. orders
    def gen_orders(self):
        rng = self.rng("orders")
        days = [(C.ORDER_START + timedelta(days=d)) for d in range((C.ORDER_END - C.ORDER_START).days + 1)]
        day_w = []
        for i, d in enumerate(days):
            w = 1.0 + 0.35 * i / len(days)              # gentle growth trend
            w *= 1.25 if d.weekday() >= 5 else 1.0      # weekend uplift
            w *= 1.4 if (d.month == 5 and d.day >= 20) or (d.month == 9 and d.day <= 7) else 1.0  # promo events
            day_w.append(w)
        hour_w = [1, 1, 1, 1, 1, 2, 3, 5, 6, 7, 8, 8, 9, 9, 8, 8, 8, 9, 10, 11, 11, 9, 6, 3]
        drafts = []
        for _ in range(self.n_orders):
            d = rng.choices(days, weights=day_w)[0]
            placed = datetime.combine(d, time(rng.choices(range(24), weights=hour_w)[0], rng.randrange(60), rng.randrange(60)))
            drafts.append((placed, rng.random()))
        drafts.sort()
        self.orders, self.lines_by_order, self.order_lines = {}, {}, {}
        for placed, _ in drafts:
            oid = self.next_id("ORD")
            cid = rng.choices(self.customer_ids, cum_weights=self.customer_cum)[0]
            cust = self.customers[cid]
            channel = wchoice(rng, {"WEB": 55, "APP": 35, "STORE": 10})
            n_lines = rng.choices([1, 2, 3, 4, 5], weights=[45, 28, 15, 8, 4])[0]
            used, lines = set(), []
            while len(lines) < n_lines:
                cat = wchoice(rng, C.CATEGORY_WEIGHTS)
                sku = rng.choice(self.products_by_cat[cat])
                if sku in used:
                    continue
                used.add(sku)
                if cat == "GIFT_CARD":
                    qty = 1
                elif cat in ("APPAREL", "GROCERY"):
                    qty = rng.choices([1, 2, 3, 4], weights=[60, 24, 10, 6])[0]
                else:
                    qty = rng.choices([1, 2, 3, 4], weights=[78, 15, 5, 2])[0]
                price = self.products[sku]["list_price"]
                gross = qty * price
                final_sale = False
                disc = 0
                if cat != "GIFT_CARD":
                    r = rng.random()
                    if r < 0.05:
                        final_sale = True
                        disc = apply_rate(gross, rng.choice([40, 50, 60]) * 100)
                    elif r < 0.30:
                        disc = apply_rate(gross, rng.choice([5, 10, 15, 20, 25, 30]) * 100)
                lines.append({"sku": sku, "category": cat, "qty": qty, "unit_price": price,
                              "line_discount": disc, "is_final_sale": final_sale})
            # Order-level coupon, allocated pro-rata to non-gift-card lines; remainder to largest line.
            eligible = [ln for ln in lines if ln["category"] != "GIFT_CARD"]
            base = sum(ln["qty"] * ln["unit_price"] - ln["line_discount"] for ln in eligible)
            promo, coupon = None, 0
            if eligible and rng.random() < 0.18:
                promo = wchoice(rng, {"SAVE10": 50, "FLAT15": 25, "WELCOME5": 25})
                if promo == "SAVE10":
                    coupon = apply_rate(base, 1000)
                elif promo == "FLAT15":
                    coupon = 1500 if base >= 7500 else 0
                else:
                    coupon = min(500, base)
                if coupon == 0:
                    promo = None
            for ln in lines:
                ln["allocated_order_discount"] = 0
            if coupon:
                largest = max(eligible, key=lambda ln: ln["qty"] * ln["unit_price"] - ln["line_discount"])
                allocated = 0
                for ln in eligible:
                    if ln is largest:
                        continue
                    share = half_up_div(coupon * (ln["qty"] * ln["unit_price"] - ln["line_discount"]), base)
                    ln["allocated_order_discount"] = share
                    allocated += share
                largest["allocated_order_discount"] = coupon - allocated
            tax_bp = C.STATE_TAX_BP[cust["home_state"]]
            for ln in lines:
                ln["net_amount"] = ln["qty"] * ln["unit_price"] - ln["line_discount"] - ln["allocated_order_discount"]
                ln["tax_amount"] = 0 if ln["category"] in C.TAX_EXEMPT_CATEGORIES else apply_rate(ln["net_amount"], tax_bp)
                ln["line_total"] = ln["net_amount"] + ln["tax_amount"]
            merch = sum(ln["net_amount"] for ln in lines)
            all_gift = all(ln["category"] == "GIFT_CARD" for ln in lines)
            shipping = 0 if channel == "STORE" or all_gift or merch >= C.FREE_SHIPPING_THRESHOLD_CENTS else C.STANDARD_SHIPPING_CENTS
            if channel == "STORE":
                shipped = delivered = placed
            else:
                shipped = placed + minutes(rng, 240, 48 * 60)
                delivered = shipped + timedelta(days=rng.randint(1, 6), minutes=rng.randint(0, 600))
            order = {
                "order_id": oid, "customer_id": cid, "order_type": "SALE", "source_rma_id": None,
                "order_channel": channel, "placed_at": placed, "shipped_at": shipped, "delivered_at": delivered,
                "ship_state": cust["home_state"], "tax_rate": tax_bp, "promo_code": promo,
                "payment_method": wchoice(rng, {"CARD": 70, "PAYPAL": 15, "APPLE_PAY": 10, "GIFT_CARD_BALANCE": 5}),
                "items_subtotal": sum(ln["qty"] * ln["unit_price"] for ln in lines),
                "line_discount_total": sum(ln["line_discount"] for ln in lines),
                "order_discount": coupon, "shipping_fee": shipping,
                "tax_total": sum(ln["tax_amount"] for ln in lines),
                "order_total": merch + sum(ln["tax_amount"] for ln in lines) + shipping,
                "current_status": None,
            }
            self.t["orders"].append(order)
            self.orders[oid] = order
            self.lines_by_order[oid] = []
            for no, ln in enumerate(lines, 1):
                row = {"order_line_id": f"ORDL-{oid[4:]}-{no:02d}", "order_id": oid, "line_no": no, **ln}
                row = {k: row[k] for k in ["order_line_id", "order_id", "line_no", "sku", "category", "qty",
                                           "unit_price", "line_discount", "allocated_order_discount",
                                           "net_amount", "tax_amount", "line_total", "is_final_sale"]}
                self.t["order_line"].append(row)
                self.order_lines[row["order_line_id"]] = row
                self.lines_by_order[oid].append(row)
            self.event("ORDER", oid, None, "PLACED", placed, "CUSTOMER", cid)
            self.event("ORDER", oid, "PLACED", "SHIPPED", shipped, "SYSTEM")
            self.event("ORDER", oid, "SHIPPED", "DELIVERED", delivered, "CARRIER")

    # ------------------------------------------------------- 3. return requests
    def line_policy(self, ol):
        return P.policy_for(self.policies, ol["category"], self.orders[ol["order_id"]]["placed_at"].date())

    def gen_return_requests(self):
        rng = self.rng("returns")
        cutoff = C.AS_OF - timedelta(days=3)
        candidates = [o for o in self.t["orders"] if o["order_type"] == "SALE" and o["delivered_at"] <= cutoff]
        weights = []
        for o in candidates:
            lines = self.lines_by_order[o["order_id"]]
            weights.append(max(C.RETURN_PROPENSITY[ln["category"]] for ln in lines) * (1 + 0.15 * (len(lines) - 1)))
        n_second = round(self.n_requests * SECOND_RMA_SHARE)
        n_first = self.n_requests - n_second
        chosen = weighted_sample(rng, candidates, weights, n_first)

        def pick_line(lines, exclude=()):
            pool = [ln for ln in lines if ln["order_line_id"] not in exclude]
            return rng.choices(pool, weights=[C.RETURN_PROPENSITY[ln["category"]] for ln in pool])[0]

        slots = []
        for o in chosen:
            lines = self.lines_by_order[o["order_id"]]
            anchor = pick_line(lines)
            cust = self.customers[o["customer_id"]]
            pol = self.line_policy(anchor)
            window = P.effective_window(pol, cust["loyalty_tier"])
            if window < 7:
                window = 30
            delivered = o["delivered_at"].date()
            max_offset = (C.AS_OF.date() - delivered).days - 1
            late = rng.random() < LATE_SHARE
            if late:
                offset = window + 1 if rng.random() < 0.25 else window + 2 + int(rng.expovariate(1 / 12))
                offset = min(offset, window + 60)
                if offset > max_offset:
                    late = False
            if not late:
                offset = window if rng.random() < 0.04 else 1 + int(rng.betavariate(1.2, 3.0) * max(window - 1, 0))
            offset = max(1, min(offset, max_offset))
            req_at = datetime.combine(delivered + timedelta(days=offset), time(rng.randint(7, 22), rng.randrange(60)))
            slots.append({"order": o, "lines": [anchor], "requested_at": req_at, "first": None})

        firsts = [s for s in slots if (C.AS_OF - s["requested_at"]).days >= 4]
        for s in rng.sample(firsts, min(n_second, len(firsts))):
            max_gap = min(25, (C.AS_OF - s["requested_at"]).days - 1)
            req_at = s["requested_at"] + timedelta(days=rng.randint(3, max_gap), hours=rng.randint(-3, 3))
            lines = self.lines_by_order[s["order"]["order_id"]]
            anchor = rng.choice(s["lines"]) if rng.random() < 0.6 else pick_line(lines)
            slots.append({"order": s["order"], "lines": [anchor], "requested_at": req_at, "first": s})

        # Distribute extra lines so the total equals the target return-line volume exactly.
        extra = self.n_lines - len(slots)
        open_slots = [s for s in slots if len(self.lines_by_order[s["order"]["order_id"]]) > 1]
        while extra > 0 and open_slots:
            i = rng.randrange(len(open_slots))
            s = open_slots[i]
            lines = self.lines_by_order[s["order"]["order_id"]]
            s["lines"].append(pick_line(lines, {ln["order_line_id"] for ln in s["lines"]}))
            extra -= 1
            if len(s["lines"]) == len(lines):
                open_slots[i] = open_slots[-1]
                open_slots.pop()

        slots.sort(key=lambda s: (s["requested_at"], s["order"]["order_id"]))
        self.rma_lines = {}
        self.requests = {}
        requested_by_slot_line = {}
        for s in slots:
            rma_id = self.next_id("RMA")
            s["rma_id"] = rma_id
            o = s["order"]
            cust = self.customers[o["customer_id"]]
            reasons_fit = []
            rows = []
            for no, ol in enumerate(sorted(s["lines"], key=lambda x: x["line_no"]), 1):
                fit = ol["category"] in ("APPAREL", "SPORTS")
                reason = wchoice(rng, REASON_WEIGHTS_FIT if fit else REASON_WEIGHTS_OTHER)
                reasons_fit.append(reason)
                qty = ol["qty"]
                prev = requested_by_slot_line.get((id(s["first"]), ol["order_line_id"])) if s["first"] else None
                if prev is not None:
                    remaining = qty - prev
                    req_qty = remaining if remaining > 0 and rng.random() < 0.6 else qty
                else:
                    req_qty = qty
                    if qty > 1 and rng.random() < 0.45:
                        req_qty = rng.randint(1, qty - 1)
                    if rng.random() < 0.02:
                        req_qty = qty + 1
                requested_by_slot_line[(id(s), ol["order_line_id"])] = req_qty
                rows.append({
                    "return_line_id": f"RMAL-{rma_id}-{no:02d}", "rma_id": rma_id,
                    "order_line_id": ol["order_line_id"], "sku": ol["sku"], "requested_qty": req_qty,
                    "return_reason": reason, "item_opened": rng.random() < OPENED_PROB[reason],
                })
            any_late = any(
                (s["requested_at"].date() - o["delivered_at"].date()).days
                > P.effective_window(self.line_policy(self.order_lines[r["order_line_id"]]), cust["loyalty_tier"])
                for r in rows)
            override = any_late and rng.random() < OVERRIDE_SHARE
            if "WRONG_SIZE" in reasons_fit and rng.random() < 0.45:
                resolution = "EXCHANGE"
            else:
                resolution = wchoice(rng, {"REFUND": 81, "EXCHANGE": 12, "STORE_CREDIT": 7})
            req = {
                "rma_id": rma_id, "order_id": o["order_id"], "customer_id": o["customer_id"],
                "requested_at": s["requested_at"],
                "return_channel": wchoice(rng, {"WEB": 50, "APP": 30, "STORE": 12, "CALL_CENTER": 8}),
                "resolution_type": resolution, "late_override_flag": override,
                "override_by": rng.choice(C.OPS_MANAGERS) if override else None,
                "override_reason": wchoice(rng, {"LOYAL_CUSTOMER": 40, "CARRIER_DELAY": 35, "SERVICE_RECOVERY": 25}) if override else None,
                "current_status": None,
            }
            self.t["return_request"].append(req)
            self.requests[rma_id] = req
            self.rma_lines[rma_id] = rows
            self.t["return_line"].extend(rows)

    # ---------------------------------------------------------- 4. decisions
    def decide(self, req, rl, prior):
        ol = self.order_lines[rl["order_line_id"]]
        o = self.orders[req["order_id"]]
        return P.decide_line(
            policy=self.line_policy(ol), loyalty_tier=self.customers[req["customer_id"]]["loyalty_tier"],
            delivered_date=o["delivered_at"].date(), requested_date=req["requested_at"].date(),
            purchased_qty=ol["qty"], prior_approved_qty=prior, requested_qty=rl["requested_qty"],
            return_reason=rl["return_reason"], item_opened=rl["item_opened"],
            is_final_sale=ol["is_final_sale"], late_override=req["late_override_flag"])

    def gen_authorizations(self):
        rng = self.rng("authorizations")
        prior_approved = {}
        self.auth_by_rma = {}
        self.auth_lines = {}
        for req in self.t["return_request"]:
            rma_id = req["rma_id"]
            if req["late_override_flag"]:
                decided_at, role = req["requested_at"] + minutes(rng, 240, 72 * 60), "OPS_MANAGER"
            else:
                decided_at, role = req["requested_at"] + minutes(rng, 5, 36 * 60), "SYSTEM_RULES"
            decisions = []
            for rl in self.rma_lines[rma_id]:
                d = self.decide(req, rl, prior_approved.get(rl["order_line_id"], 0))
                decisions.append((rl, d))
                self.gt_labels[rl["return_line_id"]] = {
                    "return_line_id": rl["return_line_id"], "rma_id": rma_id,
                    "expected_line_decision": d.line_decision, "expected_approved_qty": d.approved_qty,
                    "expected_decision_reason": d.decision_reason, "expected_override_applied": d.override_applied,
                    "decision_recorded": decided_at <= C.AS_OF,
                    "expected_disposition": None, "expected_line_refund_amount": None,
                    "is_anomaly": False, "anomaly_issue_types": "",
                }
            if decided_at > C.AS_OF:
                continue  # still pending review at the as-of date
            auth_id = self.next_id("RA")
            auth = {"authorization_id": auth_id, "rma_id": rma_id, "decided_at": decided_at,
                    "decided_by_role": role, "decision_status": None, "approved_qty_total": 0,
                    "label_expires_at": None}
            self.t["return_authorization"].append(auth)
            self.auth_by_rma[rma_id] = auth
            for rl, d in decisions:
                prior_approved[rl["order_line_id"]] = prior_approved.get(rl["order_line_id"], 0) + d.approved_qty
                al = {"authorization_line_id": "RAL-" + rl["return_line_id"][5:], "authorization_id": auth_id,
                      "return_line_id": rl["return_line_id"], "policy_id": d.policy_id,
                      "days_since_delivery": d.days_since_delivery, "effective_window_days": d.effective_window_days,
                      "prior_approved_qty": d.prior_approved_qty, "approved_qty": d.approved_qty,
                      "line_decision": d.line_decision, "decision_reason": d.decision_reason,
                      "override_applied": d.override_applied}
                self.t["authorization_line"].append(al)
                self.auth_lines[rl["return_line_id"]] = al
            self.refresh_authorization(auth)

    def refresh_authorization(self, auth):
        lines = [self.auth_lines[rl["return_line_id"]] for rl in self.rma_lines[auth["rma_id"]]]
        auth["decision_status"] = P.authorization_status([al["line_decision"] for al in lines])
        auth["approved_qty_total"] = sum(al["approved_qty"] for al in lines)
        auth["label_expires_at"] = (auth["decided_at"] + timedelta(days=C.LABEL_VALIDITY_DAYS)
                                    if auth["approved_qty_total"] > 0 else None)

    # ------------------------------------------------------------ 6. downstream
    def gen_downstream(self):
        rng = self.rng("downstream")
        self.refunded_by_line = {}
        self.shipping_refunded = set()
        self.inspections_by_line = {}
        self.refunds_by_rma = {}
        for req in self.t["return_request"]:
            rma_id = req["rma_id"]
            self.event("RETURN_REQUEST", rma_id, None, "SUBMITTED", req["requested_at"], "CUSTOMER", req["customer_id"])
            auth = self.auth_by_rma.get(rma_id)
            if auth is None:
                continue
            actor = "OPS_MANAGER" if auth["decided_by_role"] == "OPS_MANAGER" else "SYSTEM"
            self.event("RETURN_REQUEST", rma_id, "SUBMITTED", auth["decision_status"], auth["decided_at"], actor,
                       req["override_by"] if actor == "OPS_MANAGER" else None)
            if auth["approved_qty_total"] == 0:
                continue
            self.process_rma(rng, req, auth)

    def process_rma(self, rng, req, auth):
        rma_id = req["rma_id"]
        approved = [(rl, self.auth_lines[rl["return_line_id"]]) for rl in self.rma_lines[rma_id]
                    if self.auth_lines[rl["return_line_id"]]["approved_qty"] > 0]
        store = req["return_channel"] == "STORE"
        warehouse = rng.choice(C.WAREHOUSES)
        missing = rng.random() < MISSING_SHIPMENT_SHARE
        if not missing and len(approved) >= 2 and rng.random() < SPLIT_SHARE:
            k = rng.randint(1, len(approved) - 1)
            groups = [approved[:k], approved[k:]]
        else:
            groups = [approved]
        lost = not missing and len(groups) == 1 and rng.random() < LOST_SHARE

        shipments = []
        for group in groups:
            carrier = "STORE_DROPOFF" if store else wchoice(rng, C.CARRIERS)
            sid = self.next_id("RTS")
            label_at = auth["decided_at"] + minutes(rng, 1, 30)
            ship = {"shipment_id": sid, "rma_id": rma_id, "authorization_id": auth["authorization_id"],
                    "carrier": carrier,
                    "tracking_number": f"{TRACKING_PREFIX[carrier]}{self.counters['RTS']:010d}{rng.randrange(100):02d}",
                    "warehouse_id": warehouse, "label_created_at": label_at, "shipped_at": None,
                    "received_at": None, "current_status": None}
            self.t["return_shipment"].append(ship)
            self.event("RETURN_SHIPMENT", sid, None, "LABEL_CREATED", label_at, "SYSTEM")
            for rl, al in group:
                self.t["shipment_line"].append({"shipment_id": sid, "return_line_id": rl["return_line_id"],
                                                "shipped_qty": al["approved_qty"]})
            shipments.append((ship, group))
            if missing:
                if auth["label_expires_at"] <= C.AS_OF:
                    self.event("RETURN_SHIPMENT", sid, "LABEL_CREATED", "EXPIRED", auth["label_expires_at"], "SYSTEM",
                               reason="LABEL_NOT_SCANNED")
                    self.event("RETURN_REQUEST", rma_id, auth["decision_status"], "EXPIRED", auth["label_expires_at"],
                               "SYSTEM", reason="NO_SHIPMENT_RECEIVED")
                return
            max_ship_days = 5 if store else 12
            shipped_at = label_at + timedelta(days=rng.randint(0, max_ship_days), minutes=rng.randint(30, 600))
            shipped_at = min(shipped_at, auth["label_expires_at"])
            if shipped_at > C.AS_OF:
                continue
            ship["shipped_at"] = shipped_at
            self.event("RETURN_SHIPMENT", sid, "LABEL_CREATED", "IN_TRANSIT", shipped_at, "CARRIER")

        shipped = [s for s, _ in shipments if s["shipped_at"]]
        if not shipped:
            return
        self.event("RETURN_REQUEST", rma_id, auth["decision_status"], "IN_TRANSIT",
                   min(s["shipped_at"] for s in shipped), "CARRIER")
        if lost:
            ship = shipments[0][0]
            lost_at = ship["shipped_at"] + timedelta(days=C.LOST_TRACE_DAYS)
            if lost_at <= C.AS_OF:
                self.event("RETURN_SHIPMENT", ship["shipment_id"], "IN_TRANSIT", "LOST", lost_at, "CARRIER",
                           reason="TRACE_CLOSED_NO_DELIVERY")
                self.event("RETURN_REQUEST", rma_id, "IN_TRANSIT", "LOST_IN_TRANSIT", lost_at, "SYSTEM",
                           reason="CARRIER_LOST")
            return

        inspections = []
        all_done = len(shipped) == len(shipments)
        for ship, group in shipments:
            if not ship["shipped_at"]:
                continue
            transit = rng.randint(1, 3) if store else rng.randint(2, 7)
            received_at = ship["shipped_at"] + timedelta(days=transit, minutes=rng.randint(0, 480))
            if received_at > C.AS_OF:
                all_done = False
                continue
            ship["received_at"] = received_at
            self.event("RETURN_SHIPMENT", ship["shipment_id"], "IN_TRANSIT", "RECEIVED", received_at,
                       "WAREHOUSE_OPERATOR")
            for rl, al in group:
                inspected_at = received_at + minutes(rng, 120, 72 * 60)
                if inspected_at > C.AS_OF:
                    all_done = False
                    continue
                inspections.append(self.make_inspection(rng, ship, rl, al, inspected_at))
        received = [s for s, _ in shipments if s["received_at"]]
        if received and len(received) == len(shipments):
            self.event("RETURN_REQUEST", rma_id, "IN_TRANSIT", "RECEIVED", max(s["received_at"] for s in received),
                       "WAREHOUSE_OPERATOR")
        if not all_done or not inspections:
            return
        inspected_at = max(i["inspected_at"] for i in inspections)
        self.event("RETURN_REQUEST", rma_id, "RECEIVED", "INSPECTED", inspected_at, "WAREHOUSE_OPERATOR")
        self.resolve(rng, req, inspections, inspected_at)

    def make_inspection(self, rng, ship, rl, al, inspected_at):
        reason, opened = rl["return_reason"], rl["item_opened"]
        if reason == "DEFECTIVE":
            cond = wchoice(rng, {"DEFECTIVE": 85, "OPENED_LIKE_NEW": 15})
        elif reason == "DAMAGED_IN_TRANSIT":
            cond = wchoice(rng, {"DAMAGED": 90, "OPENED_LIKE_NEW": 10})
        elif reason == "WRONG_ITEM":
            cond = wchoice(rng, {"UNOPENED": 70, "OPENED_LIKE_NEW": 30})
        elif not opened:
            cond = wchoice(rng, {"UNOPENED": 88, "OPENED_LIKE_NEW": 7, "DAMAGED": 3, "NOT_ORIGINAL_ITEM": 2})
        else:
            cond = wchoice(rng, {"OPENED_LIKE_NEW": 80, "DAMAGED": 14, "DEFECTIVE": 3, "NOT_ORIGINAL_ITEM": 3})
        shipped_qty = al["approved_qty"]
        received_qty = shipped_qty - 1 if shipped_qty >= 2 and rng.random() < SHORTAGE_SHARE else shipped_qty
        attribution = P.damage_attribution(cond, reason)
        ins = {"inspection_id": self.next_id("INS"), "shipment_id": ship["shipment_id"],
               "return_line_id": rl["return_line_id"], "inspector_id": rng.choice(C.INSPECTORS),
               "inspected_at": inspected_at, "received_qty": received_qty, "condition_grade": cond,
               "damage_attribution": attribution,
               "inspection_result": P.inspection_result(cond, attribution, received_qty, shipped_qty)}
        self.t["inspection"].append(ins)
        self.inspections_by_line.setdefault(rl["return_line_id"], []).append(ins)
        ol = self.order_lines[rl["order_line_id"]]
        disposition = P.decide_disposition(ol["category"], cond, ol["unit_price"])
        decided_at = inspected_at + minutes(rng, 60, 48 * 60)
        if received_qty > 0 and decided_at <= C.AS_OF:
            did = self.next_id("DISP")
            self.t["inventory_disposition"].append({
                "disposition_id": did, "inspection_id": ins["inspection_id"], "return_line_id": rl["return_line_id"],
                "sku": rl["sku"], "qty": received_qty, "disposition": disposition, "decided_at": decided_at,
                "decided_by": ins["inspector_id"]})
            cost = self.products[rl["sku"]]["unit_cost"]
            self.t["inventory_movement"].append({
                "movement_id": self.next_id("IMV"), "disposition_id": did, "sku": rl["sku"],
                "warehouse_id": ship["warehouse_id"], "from_location": "RETURNS_DOCK",
                "to_location": P.DISPOSITION_LOCATION[disposition], "qty": received_qty, "unit_cost": cost,
                "movement_value": received_qty * cost, "moved_at": decided_at})
        return ins

    def resolve(self, rng, req, inspections, inspected_at):
        rma_id = req["rma_id"]
        rl_by_id = {rl["return_line_id"]: rl for rl in self.rma_lines[rma_id]}
        if req["resolution_type"] == "EXCHANGE" and all(i["inspection_result"] == "PASS" for i in inspections):
            placed = inspected_at + minutes(rng, 60, 20 * 60)
            if placed <= C.AS_OF:
                self.make_exchange_order(rng, req, inspections, rl_by_id, placed)
                self.event("RETURN_REQUEST", rma_id, "INSPECTED", "EXCHANGED", placed, "SYSTEM")
            return
        order = self.orders[req["order_id"]]
        method = "STORE_CREDIT" if req["resolution_type"] == "STORE_CREDIT" else "ORIGINAL_PAYMENT"
        calcs, any_mf = [], False
        for ins in inspections:
            rl = rl_by_id[ins["return_line_id"]]
            ol = self.order_lines[rl["order_line_id"]]
            pol = self.line_policy(ol)
            c = P.refund_line(net_amount=ol["net_amount"], tax_amount=ol["tax_amount"], purchased_qty=ol["qty"],
                              refund_qty=ins["received_qty"], condition=ins["condition_grade"],
                              attribution=ins["damage_attribution"], return_reason=rl["return_reason"],
                              restocking_fee_rate=pol.restocking_fee_rate,
                              already_refunded=self.refunded_by_line.get(ol["order_line_id"], 0))
            any_mf = any_mf or P.merchant_fault_confirmed(ins["condition_grade"], ins["damage_attribution"],
                                                          rl["return_reason"])
            calcs.append((ins, rl, ol, c))
        lines_amount = sum(c.line_refund_amount for *_, c in calcs)
        ship_refund, label_fee, amount = P.refund_header(
            lines_amount=lines_amount, any_merchant_fault=any_mf, shipping_fee=order["shipping_fee"],
            shipping_already_refunded=order["order_id"] in self.shipping_refunded, refund_method=method,
            return_channel=req["return_channel"])
        if amount == 0:
            self.event("RETURN_REQUEST", rma_id, "INSPECTED", "CLOSED_NO_REFUND", inspected_at + minutes(rng, 10, 120),
                       "SYSTEM", reason="NOTHING_REFUNDABLE")
            return
        requested_at = inspected_at + minutes(rng, 10, 360)
        if requested_at > C.AS_OF:
            return
        processed_at = requested_at + minutes(rng, 60, 72 * 60)
        paid = processed_at <= C.AS_OF
        key = f"{rma_id}:REFUND:1"
        ref = self.make_refund(rma_id, key, 1, method, requested_at, processed_at if paid else None,
                               lines_amount, ship_refund, label_fee, amount, "PAID" if paid else "REQUESTED", calcs)
        for _, _, ol, c in calcs:
            self.refunded_by_line[ol["order_line_id"]] = self.refunded_by_line.get(ol["order_line_id"], 0) + c.line_refund_amount
        if ship_refund:
            self.shipping_refunded.add(order["order_id"])
        if paid:
            self.event("RETURN_REQUEST", rma_id, "INSPECTED", "REFUNDED", processed_at, "PAYMENT_GATEWAY", ref["refund_id"])
            if rng.random() < BLOCKED_RETRY_SHARE:
                retry_at = requested_at + minutes(rng, 1, 30)
                self.make_refund(rma_id, key, 2, method, retry_at, retry_at, lines_amount, ship_refund, label_fee,
                                 amount, "BLOCKED_DUPLICATE", calcs, blocked="IDEMPOTENCY_KEY_ALREADY_USED")

    def make_refund(self, rma_id, key, seq, method, requested_at, processed_at, lines_amount, ship_refund,
                    label_fee, amount, status, calcs, blocked=None):
        rid = self.next_id("REF")
        ref = {"refund_id": rid, "rma_id": rma_id, "idempotency_key": key, "attempt_seq": seq,
               "refund_method": method, "requested_at": requested_at, "processed_at": processed_at,
               "lines_amount": lines_amount, "shipping_refund": ship_refund, "return_label_fee": label_fee,
               "refund_amount": amount, "paid_amount": amount if status == "PAID" else 0,
               "current_status": None, "blocked_reason": blocked}
        self.t["refund"].append(ref)
        self.refunds_by_rma.setdefault(rma_id, []).append(ref)
        for n, (ins, rl, ol, c) in enumerate(calcs, 1):
            self.t["refund_line"].append({
                "refund_line_id": f"REFL-{rid}-{n:02d}", "refund_id": rid, "return_line_id": rl["return_line_id"],
                "inspection_id": ins["inspection_id"], "order_line_id": ol["order_line_id"],
                "refund_qty": ins["received_qty"], "merchandise_amount": c.merchandise_amount,
                "tax_amount": c.tax_amount, "restocking_fee": c.restocking_fee,
                "damage_deduction": c.damage_deduction, "cap_adjustment": c.cap_adjustment,
                "line_refund_amount": c.line_refund_amount})
        self.event("REFUND", rid, None, "REQUESTED", requested_at, "SYSTEM", reason=key)
        if status != "REQUESTED":
            self.event("REFUND", rid, "REQUESTED", status, processed_at, "PAYMENT_GATEWAY", reason=blocked)
        return ref

    def make_exchange_order(self, rng, req, inspections, rl_by_id, placed):
        orig = self.orders[req["order_id"]]
        oid = f"ORD-2026-{self.n_orders + self.counters.get('EXCH', 0) + 1:06d}"
        self.counters["EXCH"] = self.counters.get("EXCH", 0) + 1
        shipped = placed + minutes(rng, 240, 36 * 60)
        delivered = shipped + timedelta(days=rng.randint(1, 5), minutes=rng.randint(0, 600))
        lines = []
        for no, ins in enumerate(inspections, 1):
            rl = rl_by_id[ins["return_line_id"]]
            ol = self.order_lines[rl["order_line_id"]]
            gross = ins["received_qty"] * ol["unit_price"]
            lines.append({"order_line_id": f"ORDL-{oid[4:]}-{no:02d}", "order_id": oid, "line_no": no,
                          "sku": ol["sku"], "category": ol["category"], "qty": ins["received_qty"],
                          "unit_price": ol["unit_price"], "line_discount": gross, "allocated_order_discount": 0,
                          "net_amount": 0, "tax_amount": 0, "line_total": 0, "is_final_sale": False})
        order = {"order_id": oid, "customer_id": orig["customer_id"], "order_type": "EXCHANGE",
                 "source_rma_id": req["rma_id"], "order_channel": "WEB", "placed_at": placed,
                 "shipped_at": shipped if shipped <= C.AS_OF else None,
                 "delivered_at": delivered if delivered <= C.AS_OF else None,
                 "ship_state": orig["ship_state"], "tax_rate": orig["tax_rate"], "promo_code": None,
                 "payment_method": "EXCHANGE_CREDIT", "items_subtotal": sum(l["line_discount"] for l in lines),
                 "line_discount_total": sum(l["line_discount"] for l in lines), "order_discount": 0,
                 "shipping_fee": 0, "tax_total": 0, "order_total": 0, "current_status": None}
        self.t["orders"].append(order)
        self.orders[oid] = order
        self.lines_by_order[oid] = lines
        for ln in lines:
            self.t["order_line"].append(ln)
            self.order_lines[ln["order_line_id"]] = ln
        self.event("ORDER", oid, None, "PLACED", placed, "SYSTEM", reason=req["rma_id"])
        if order["shipped_at"]:
            self.event("ORDER", oid, "PLACED", "SHIPPED", shipped, "SYSTEM")
        if order["delivered_at"]:
            self.event("ORDER", oid, "SHIPPED", "DELIVERED", delivered, "CARRIER")

    # ------------------------------------------------ expected outcome labels
    def record_expected_outcomes(self):
        """Snapshot of clean, rule-derived outcomes before post-process anomalies are injected."""
        disp_by_ins = {d["inspection_id"]: d["disposition"] for d in self.t["inventory_disposition"]}
        first_attempts = {r["refund_id"] for r in self.t["refund"] if r["attempt_seq"] == 1}
        paid_lines = {}
        for rf in self.t["refund_line"]:
            if rf["refund_id"] in first_attempts:
                paid_lines[rf["return_line_id"]] = paid_lines.get(rf["return_line_id"], 0) + rf["line_refund_amount"]
        for rl_id, label in self.gt_labels.items():
            ins = self.inspections_by_line.get(rl_id, [])
            if ins:
                label["expected_disposition"] = ";".join(
                    disp_by_ins[i["inspection_id"]] for i in ins if i["inspection_id"] in disp_by_ins) or None
            if rl_id in paid_lines:
                label["expected_line_refund_amount"] = paid_lines[rl_id]

    # --------------------------------------------------------------- finalize
    def finalize(self):
        self.events.sort(key=lambda e: (e["event_ts"], e["_seq"]))
        last = {}
        for n, e in enumerate(self.events, 1):
            e["event_id"] = f"EVT-2026-{n:07d}"
            del e["_seq"]
            last[(e["entity_type"], e["entity_id"])] = e["to_status"]
        self.t["status_event"] = [{k: e[k] for k in ["event_id", "entity_type", "entity_id", "from_status",
                                                     "to_status", "event_ts", "actor_role", "actor_id",
                                                     "reason_code"]} for e in self.events]
        for table, etype, pk in [("orders", "ORDER", "order_id"), ("return_request", "RETURN_REQUEST", "rma_id"),
                                 ("return_shipment", "RETURN_SHIPMENT", "shipment_id"), ("refund", "REFUND", "refund_id")]:
            for row in self.t[table]:
                row["current_status"] = last[(etype, row[pk])]
        for tab in TABLES:
            self.t[tab.name].sort(key=lambda r, pk=tab.pk: tuple(r[c] for c in pk))
            self.t[tab.name] = [{c: r[c] for c in tab.columns} for r in self.t[tab.name]]


def generate(seed=C.DEFAULT_SEED, scale=1.0):
    return Generator(seed, scale).run()
