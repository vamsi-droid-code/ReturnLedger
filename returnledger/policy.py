"""Business rules. Pure functions, no randomness.

The generator uses these to produce *correct* baseline decisions, and the audit uses the
very same functions to re-derive what *should* have happened from raw input tables.
"""
from dataclasses import dataclass
from datetime import date

from . import config as C
from .money import apply_rate, prorate


# --------------------------------------------------------------------------- policies
@dataclass(frozen=True)
class Policy:
    policy_id: str
    category: str
    version: int
    effective_from: date
    effective_to: object
    return_window_days: int
    returnable: bool
    opened_returnable: bool
    restocking_fee_rate: int  # basis points
    merchant_fault_override: bool


def build_policies():
    out = []
    for (cat, ver, eff_from, eff_to, window, returnable, opened_ok, fee_bp, mf) in C.RETURN_POLICIES:
        out.append(Policy(f"POL-{cat}-V{ver}", cat, ver, eff_from, eff_to, window,
                          returnable, opened_ok, fee_bp, mf))
    return out


def policy_for(policies, category: str, order_date: date) -> Policy:
    """Effective-dated lookup: the policy in force on the order's placed date."""
    for p in policies:
        if p.category == category and p.effective_from <= order_date and (
                p.effective_to is None or order_date <= p.effective_to):
            return p
    raise LookupError(f"no policy for {category} on {order_date}")


# ------------------------------------------------------------------------ eligibility
@dataclass(frozen=True)
class LineDecision:
    policy_id: str
    days_since_delivery: int
    effective_window_days: int
    prior_approved_qty: int
    approved_qty: int
    line_decision: str
    decision_reason: str
    override_applied: bool


def effective_window(policy: Policy, loyalty_tier: str) -> int:
    return policy.return_window_days + C.LOYALTY_WINDOW_EXTENSION_DAYS[loyalty_tier]


def decide_line(*, policy: Policy, loyalty_tier: str, delivered_date: date, requested_date: date,
                purchased_qty: int, prior_approved_qty: int, requested_qty: int,
                return_reason: str, item_opened: bool, is_final_sale: bool,
                late_override: bool) -> LineDecision:
    """Eligibility rules, evaluated in a fixed precedence order:

    1. Category exclusion (not returnable) unless merchant fault and the policy allows it.
    2. Final-sale (clearance) lines unless merchant fault.
    3. Opened item where policy forbids opened returns (hygiene) unless merchant fault.
    4. Return window (policy window + loyalty extension); late is rejected unless a manager
       override is recorded on the request. Day == window is still on time.
    5. Quantity: approve min(requested, purchased - previously approved); reject if nothing left.
    """
    days = (requested_date - delivered_date).days
    window = effective_window(policy, loyalty_tier)
    mf_claim = return_reason in C.MERCHANT_FAULT_REASONS
    remaining = max(purchased_qty - prior_approved_qty, 0)

    def out(qty, decision, reason, override=False):
        return LineDecision(policy.policy_id, days, window, prior_approved_qty, qty, decision, reason, override)

    if not policy.returnable and not (policy.merchant_fault_override and mf_claim):
        return out(0, "REJECTED", "REJECT_EXCLUDED_CATEGORY")
    if is_final_sale and not mf_claim:
        return out(0, "REJECTED", "REJECT_FINAL_SALE")
    if item_opened and not policy.opened_returnable and not mf_claim:
        return out(0, "REJECTED", "REJECT_HYGIENE_OPENED")
    override_applied = False
    if days > window:
        if not late_override:
            return out(0, "REJECTED", "REJECT_LATE")
        override_applied = True
    if remaining <= 0:
        return out(0, "REJECTED", "REJECT_QTY_EXCEEDS_PURCHASED", override_applied)
    if requested_qty > remaining:
        return out(remaining, "PARTIALLY_APPROVED", "QTY_CAPPED", override_applied)
    return out(requested_qty, "APPROVED", "WITHIN_POLICY", override_applied)


def authorization_status(line_decisions) -> str:
    approved = [d for d in line_decisions if d != "REJECTED"]
    if not approved:
        return "REJECTED"
    if len(approved) == len(line_decisions) and all(d == "APPROVED" for d in line_decisions):
        return "AUTHORIZED"
    return "PARTIALLY_AUTHORIZED"


# ------------------------------------------------------------------------- inspection
def damage_attribution(condition: str, return_reason: str) -> str:
    if condition == "DAMAGED":
        return "CARRIER" if return_reason == "DAMAGED_IN_TRANSIT" else "CUSTOMER"
    if condition == "DEFECTIVE":
        return "MANUFACTURER"
    return "NONE"


def inspection_result(condition: str, attribution: str, received_qty: int, shipped_qty: int) -> str:
    if condition == "NOT_ORIGINAL_ITEM" or attribution == "CUSTOMER" or received_qty < shipped_qty:
        return "FAIL"
    return "PASS"


def merchant_fault_confirmed(condition: str, attribution: str, return_reason: str) -> bool:
    """Fault as confirmed by inspection (not just claimed by the customer)."""
    if attribution in ("CARRIER", "MANUFACTURER"):
        return True
    return return_reason == "WRONG_ITEM" and condition != "NOT_ORIGINAL_ITEM"


# ----------------------------------------------------------------------------- refund
@dataclass(frozen=True)
class RefundLineCalc:
    merchandise_amount: int
    tax_amount: int
    restocking_fee: int
    damage_deduction: int
    cap_adjustment: int
    line_refund_amount: int


def refund_line(*, net_amount: int, tax_amount: int, purchased_qty: int, refund_qty: int,
                condition: str, attribution: str, return_reason: str, restocking_fee_rate: int,
                already_refunded: int) -> RefundLineCalc:
    """Refund for `refund_qty` received units of an order line.

    Paid price is the line's net amount (after line promo and allocated order coupon);
    tax is refunded pro-rata on returned units. Deductions: restocking fee on opened,
    non-fault returns; 50% damage deduction for customer damage; nothing for a
    non-original item. The result is capped so cumulative refunds for the order line
    never exceed what was paid for it (net + tax).
    """
    if refund_qty <= 0 or condition == "NOT_ORIGINAL_ITEM":
        return RefundLineCalc(0, 0, 0, 0, 0, 0)
    merch = prorate(net_amount, refund_qty, purchased_qty)
    tax = prorate(tax_amount, refund_qty, purchased_qty)
    mf = merchant_fault_confirmed(condition, attribution, return_reason)
    fee = apply_rate(merch, restocking_fee_rate) if condition == "OPENED_LIKE_NEW" and not mf else 0
    deduction = apply_rate(merch, C.CUSTOMER_DAMAGE_DEDUCTION_BP) if attribution == "CUSTOMER" else 0
    raw = merch + tax - fee - deduction
    remaining = max(net_amount + tax_amount - already_refunded, 0)
    cap = max(raw - remaining, 0)
    return RefundLineCalc(merch, tax, fee, deduction, cap, raw - cap)


def refund_header(*, lines_amount: int, any_merchant_fault: bool, shipping_fee: int,
                  shipping_already_refunded: bool, refund_method: str, return_channel: str):
    """Returns (shipping_refund, return_label_fee, refund_amount)."""
    shipping_refund = shipping_fee if any_merchant_fault and not shipping_already_refunded else 0
    label_fee = 0
    if refund_method == "ORIGINAL_PAYMENT" and not any_merchant_fault and return_channel != "STORE":
        label_fee = min(C.RETURN_LABEL_FEE_CENTS, lines_amount + shipping_refund)
    return shipping_refund, label_fee, lines_amount + shipping_refund - label_fee


# ------------------------------------------------------------------------ disposition
DISPOSITION_LOCATION = {
    "RESTOCK": "SELLABLE",
    "REFURBISH": "REFURB_BENCH",
    "QUARANTINE": "QUARANTINE_CAGE",
    "SCRAP": "SCRAP_BIN",
}
# Share of unit cost recovered, used for the recovery-rate metric.
RECOVERY_FACTOR = {"RESTOCK": 1.0, "REFURBISH": 0.6, "QUARANTINE": 0.0, "SCRAP": 0.0}


def decide_disposition(category: str, condition: str, unit_price: int) -> str:
    if condition == "NOT_ORIGINAL_ITEM":
        return "QUARANTINE"  # fraud review
    if condition == "UNOPENED":
        return "SCRAP" if category == "GROCERY" else "RESTOCK"
    if condition == "OPENED_LIKE_NEW":
        if category == "ELECTRONICS":
            return "REFURBISH"
        if category in ("BEAUTY", "GROCERY"):
            return "SCRAP"  # hygiene / perishables are never resold
        return "RESTOCK"
    if condition == "DAMAGED":
        if category == "ELECTRONICS" or unit_price >= C.REFURBISH_PRICE_THRESHOLD_CENTS:
            return "REFURBISH"
        return "SCRAP"
    if condition == "DEFECTIVE":
        return "QUARANTINE" if category in ("ELECTRONICS", "TOYS", "HOME") else "SCRAP"
    raise ValueError(condition)
