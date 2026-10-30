"""Central configuration: seed, scale, reference dates, policy tables and distributions.

Everything that drives generation lives here so a reviewer can change one number and
regenerate. Money is handled internally as integer cents; rates as basis points.
"""
from datetime import date, datetime

DEFAULT_SEED = 20261022
GENERATOR_VERSION = "1.0.0"

# Data is generated "as of" this instant. Anything that would happen later is left open
# (e.g. a shipment still IN_TRANSIT), which gives a realistic in-flight pipeline.
AS_OF = datetime(2026, 10, 25, 23, 59, 59)
ORDER_START = date(2026, 1, 1)
ORDER_END = date(2026, 9, 30)

# Baseline volume at scale 1.0 (the "full" dataset). Starter uses the same generator.
FULL_VOLUME = {
    "customers": 12_000,
    "orders": 30_000,
    "return_requests": 5_000,
    "return_lines": 8_000,
}
PRODUCT_COUNT = 1_500  # reference catalogue, not scaled
SCALES = {"starter": 0.1, "full": 1.0}

# Number of each injected anomaly at scale 1.0 (minimum 5 at any scale).
ANOMALY_COUNTS_FULL = {
    "QTY_EXCEEDS_PURCHASED": 40,
    "REFUND_EXCEEDS_PAID": 40,
    "RESTOCK_BEFORE_INSPECTION": 40,
    "LATE_APPROVED_WITHOUT_OVERRIDE": 40,
    "DUPLICATE_REFUND": 40,
}
ANOMALY_MIN = 5

CATEGORIES = [
    "APPAREL", "ELECTRONICS", "HOME", "BEAUTY", "GROCERY",
    "TOYS", "SPORTS", "BOOKS", "JEWELRY", "GIFT_CARD",
]
# Share of catalogue / order lines per category.
CATEGORY_WEIGHTS = {
    "APPAREL": 28, "ELECTRONICS": 16, "HOME": 15, "BEAUTY": 9, "GROCERY": 7,
    "TOYS": 7, "SPORTS": 8, "BOOKS": 6, "JEWELRY": 2, "GIFT_CARD": 2,
}
# Relative likelihood that a purchased line gets returned.
RETURN_PROPENSITY = {
    "APPAREL": 3.0, "ELECTRONICS": 1.6, "HOME": 1.0, "BEAUTY": 0.6, "GROCERY": 0.2,
    "TOYS": 1.0, "SPORTS": 1.2, "BOOKS": 0.6, "JEWELRY": 1.2, "GIFT_CARD": 0.15,
}
# (min_price_cents, max_price_cents, min_cost_ratio, max_cost_ratio)
PRICE_RANGES = {
    "APPAREL": (999, 14999, 0.35, 0.55),
    "ELECTRONICS": (1999, 129999, 0.60, 0.80),
    "HOME": (999, 39999, 0.45, 0.65),
    "BEAUTY": (499, 8999, 0.30, 0.50),
    "GROCERY": (199, 4999, 0.55, 0.75),
    "TOYS": (799, 14999, 0.40, 0.60),
    "SPORTS": (999, 29999, 0.45, 0.65),
    "BOOKS": (599, 5999, 0.50, 0.70),
    "JEWELRY": (2999, 49999, 0.30, 0.50),
    "GIFT_CARD": (2500, 20000, 1.00, 1.00),
}
TAX_EXEMPT_CATEGORIES = {"GIFT_CARD", "GROCERY"}

# Return policy master data. Effective-dated: policy is chosen by the order's placed date.
# (category, version, effective_from, effective_to, window_days, returnable,
#  opened_returnable, restocking_fee_bp, merchant_fault_override)
RETURN_POLICIES = [
    ("APPAREL", 1, date(2026, 1, 1), date(2026, 6, 30), 60, True, True, 0, True),
    ("APPAREL", 2, date(2026, 7, 1), None, 45, True, True, 0, True),
    ("ELECTRONICS", 1, date(2026, 1, 1), None, 30, True, True, 1500, True),
    ("HOME", 1, date(2026, 1, 1), None, 30, True, True, 0, True),
    ("BEAUTY", 1, date(2026, 1, 1), None, 30, True, False, 0, True),
    ("GROCERY", 1, date(2026, 1, 1), None, 7, False, False, 0, True),
    ("TOYS", 1, date(2026, 1, 1), None, 30, True, True, 0, True),
    ("SPORTS", 1, date(2026, 1, 1), None, 30, True, True, 1000, True),
    ("BOOKS", 1, date(2026, 1, 1), None, 30, True, True, 0, True),
    ("JEWELRY", 1, date(2026, 1, 1), None, 14, True, True, 0, True),
    ("GIFT_CARD", 1, date(2026, 1, 1), None, 0, False, False, 0, False),
]

LOYALTY_TIERS = {"STANDARD": 70, "SILVER": 18, "GOLD": 9, "PLATINUM": 3}
LOYALTY_WINDOW_EXTENSION_DAYS = {"STANDARD": 0, "SILVER": 0, "GOLD": 15, "PLATINUM": 30}

# Sales tax by state in basis points (synthetic but plausible; 0 = no state sales tax).
STATE_TAX_BP = {
    "CA": 725, "TX": 625, "NY": 400, "FL": 600, "IL": 625, "PA": 600, "OH": 575,
    "GA": 400, "NC": 475, "MI": 600, "NJ": 663, "VA": 530, "WA": 650, "AZ": 560,
    "MA": 625, "CO": 290, "OR": 0, "MT": 0, "NH": 0, "DE": 0,
}
STATE_WEIGHTS = {
    "CA": 18, "TX": 13, "NY": 9, "FL": 10, "IL": 6, "PA": 6, "OH": 5, "GA": 5, "NC": 5,
    "MI": 4, "NJ": 4, "VA": 4, "WA": 4, "AZ": 3, "MA": 3, "CO": 3, "OR": 2, "MT": 1,
    "NH": 1, "DE": 1,
}

FREE_SHIPPING_THRESHOLD_CENTS = 5000
STANDARD_SHIPPING_CENTS = 599
RETURN_LABEL_FEE_CENTS = 699
CUSTOMER_DAMAGE_DEDUCTION_BP = 5000  # 50% of merchandise value
LABEL_VALIDITY_DAYS = 14
LOST_TRACE_DAYS = 15
REFURBISH_PRICE_THRESHOLD_CENTS = 10000

RETURN_REASONS = [
    "CHANGED_MIND", "WRONG_SIZE", "NOT_AS_DESCRIBED",
    "DEFECTIVE", "DAMAGED_IN_TRANSIT", "WRONG_ITEM",
]
# Reasons where the merchant/carrier is (claimed to be) at fault.
MERCHANT_FAULT_REASONS = {"DEFECTIVE", "DAMAGED_IN_TRANSIT", "WRONG_ITEM"}

WAREHOUSES = ["WH-01", "WH-02", "WH-03", "WH-04"]
CARRIERS = {"UPS": 40, "FEDEX": 25, "USPS": 25, "DHL": 10}
OPS_MANAGERS = [f"OPS-{i:03d}" for i in range(1, 9)]
INSPECTORS = [f"OPS-{i:03d}" for i in range(101, 141)]
