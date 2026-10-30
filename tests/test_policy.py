import unittest
from datetime import date

from returnledger import policy as P
from returnledger.money import half_up_div, prorate, fmt, parse

POLICIES = P.build_policies()


def decide(**kw):
    base = dict(
        policy=P.policy_for(POLICIES, "HOME", date(2026, 3, 1)), loyalty_tier="STANDARD",
        delivered_date=date(2026, 3, 5), requested_date=date(2026, 3, 10), purchased_qty=2,
        prior_approved_qty=0, requested_qty=1, return_reason="CHANGED_MIND", item_opened=False,
        is_final_sale=False, late_override=False,
    )
    base.update(kw)
    return P.decide_line(**base)


class MoneyTests(unittest.TestCase):
    def test_half_up(self):
        self.assertEqual(half_up_div(5, 2), 3)
        self.assertEqual(half_up_div(4, 3), 1)
        self.assertEqual(prorate(1001, 1, 2), 501)

    def test_fmt_parse_roundtrip(self):
        for c in (0, 5, 99, 100, 123456, -250):
            self.assertEqual(parse(fmt(c)), c)


class PolicyLookupTests(unittest.TestCase):
    def test_effective_dated_apparel(self):
        self.assertEqual(P.policy_for(POLICIES, "APPAREL", date(2026, 6, 30)).return_window_days, 60)
        self.assertEqual(P.policy_for(POLICIES, "APPAREL", date(2026, 7, 1)).return_window_days, 45)


class EligibilityTests(unittest.TestCase):
    def test_within_policy(self):
        d = decide()
        self.assertEqual((d.line_decision, d.approved_qty, d.decision_reason), ("APPROVED", 1, "WITHIN_POLICY"))

    def test_boundary_day_equals_window_is_on_time(self):
        d = decide(requested_date=date(2026, 4, 4))  # 30 days after delivery
        self.assertEqual(d.days_since_delivery, 30)
        self.assertEqual(d.line_decision, "APPROVED")

    def test_late_rejected(self):
        d = decide(requested_date=date(2026, 4, 5))  # 31 days
        self.assertEqual(d.decision_reason, "REJECT_LATE")

    def test_late_with_override(self):
        d = decide(requested_date=date(2026, 4, 20), late_override=True)
        self.assertEqual(d.line_decision, "APPROVED")
        self.assertTrue(d.override_applied)

    def test_gold_extension(self):
        d = decide(requested_date=date(2026, 4, 15), loyalty_tier="GOLD")  # 41 days <= 45
        self.assertEqual(d.line_decision, "APPROVED")

    def test_qty_capped_and_exceeded(self):
        self.assertEqual(decide(requested_qty=3).decision_reason, "QTY_CAPPED")
        self.assertEqual(decide(requested_qty=3).approved_qty, 2)
        d = decide(prior_approved_qty=2)
        self.assertEqual(d.decision_reason, "REJECT_QTY_EXCEEDS_PURCHASED")

    def test_exclusions(self):
        gift = P.policy_for(POLICIES, "GIFT_CARD", date(2026, 3, 1))
        self.assertEqual(decide(policy=gift, return_reason="DEFECTIVE").decision_reason, "REJECT_EXCLUDED_CATEGORY")
        grocery = P.policy_for(POLICIES, "GROCERY", date(2026, 3, 1))
        self.assertEqual(decide(policy=grocery).decision_reason, "REJECT_EXCLUDED_CATEGORY")
        self.assertEqual(decide(policy=grocery, return_reason="DAMAGED_IN_TRANSIT",
                                requested_date=date(2026, 3, 9)).line_decision, "APPROVED")
        self.assertEqual(decide(is_final_sale=True).decision_reason, "REJECT_FINAL_SALE")
        self.assertEqual(decide(is_final_sale=True, return_reason="DEFECTIVE").line_decision, "APPROVED")
        beauty = P.policy_for(POLICIES, "BEAUTY", date(2026, 3, 1))
        self.assertEqual(decide(policy=beauty, item_opened=True).decision_reason, "REJECT_HYGIENE_OPENED")

    def test_exclusion_beats_override(self):
        d = decide(is_final_sale=True, requested_date=date(2026, 5, 1), late_override=True)
        self.assertEqual(d.decision_reason, "REJECT_FINAL_SALE")

    def test_authorization_status(self):
        self.assertEqual(P.authorization_status(["APPROVED", "APPROVED"]), "AUTHORIZED")
        self.assertEqual(P.authorization_status(["APPROVED", "REJECTED"]), "PARTIALLY_AUTHORIZED")
        self.assertEqual(P.authorization_status(["PARTIALLY_APPROVED"]), "PARTIALLY_AUTHORIZED")
        self.assertEqual(P.authorization_status(["REJECTED"]), "REJECTED")


class RefundTests(unittest.TestCase):
    def calc(self, **kw):
        base = dict(net_amount=10000, tax_amount=725, purchased_qty=2, refund_qty=1, condition="UNOPENED",
                    attribution="NONE", return_reason="CHANGED_MIND", restocking_fee_rate=1500,
                    already_refunded=0)
        base.update(kw)
        return P.refund_line(**base)

    def test_full_unopened(self):
        r = self.calc()
        self.assertEqual((r.merchandise_amount, r.tax_amount, r.line_refund_amount), (5000, 363, 5363))

    def test_restocking_fee_opened(self):
        r = self.calc(condition="OPENED_LIKE_NEW")
        self.assertEqual(r.restocking_fee, 750)
        self.assertEqual(r.line_refund_amount, 5000 + 363 - 750)

    def test_no_fee_when_defective(self):
        r = self.calc(condition="DEFECTIVE", attribution="MANUFACTURER", return_reason="DEFECTIVE")
        self.assertEqual(r.restocking_fee, 0)

    def test_customer_damage(self):
        r = self.calc(condition="DAMAGED", attribution="CUSTOMER")
        self.assertEqual(r.damage_deduction, 2500)

    def test_not_original_item_zero(self):
        self.assertEqual(self.calc(condition="NOT_ORIGINAL_ITEM").line_refund_amount, 0)

    def test_cap_never_exceeds_paid(self):
        r = self.calc(refund_qty=2, already_refunded=10000)
        self.assertEqual(r.line_refund_amount, 725)
        self.assertEqual(r.cap_adjustment, 10000)

    def test_header_label_fee_and_shipping(self):
        self.assertEqual(P.refund_header(lines_amount=5000, any_merchant_fault=False, shipping_fee=599,
                                         shipping_already_refunded=False, refund_method="ORIGINAL_PAYMENT",
                                         return_channel="WEB"), (0, 699, 4301))
        self.assertEqual(P.refund_header(lines_amount=5000, any_merchant_fault=True, shipping_fee=599,
                                         shipping_already_refunded=False, refund_method="ORIGINAL_PAYMENT",
                                         return_channel="WEB"), (599, 0, 5599))
        self.assertEqual(P.refund_header(lines_amount=300, any_merchant_fault=False, shipping_fee=0,
                                         shipping_already_refunded=False, refund_method="ORIGINAL_PAYMENT",
                                         return_channel="WEB"), (0, 300, 0))


class DispositionTests(unittest.TestCase):
    def test_table(self):
        self.assertEqual(P.decide_disposition("APPAREL", "UNOPENED", 2000), "RESTOCK")
        self.assertEqual(P.decide_disposition("ELECTRONICS", "OPENED_LIKE_NEW", 2000), "REFURBISH")
        self.assertEqual(P.decide_disposition("BEAUTY", "OPENED_LIKE_NEW", 2000), "SCRAP")
        self.assertEqual(P.decide_disposition("HOME", "DAMAGED", 15000), "REFURBISH")
        self.assertEqual(P.decide_disposition("HOME", "DAMAGED", 5000), "SCRAP")
        self.assertEqual(P.decide_disposition("TOYS", "DEFECTIVE", 5000), "QUARANTINE")
        self.assertEqual(P.decide_disposition("APPAREL", "NOT_ORIGINAL_ITEM", 5000), "QUARANTINE")
        self.assertEqual(P.decide_disposition("GROCERY", "UNOPENED", 500), "SCRAP")


if __name__ == "__main__":
    unittest.main()
