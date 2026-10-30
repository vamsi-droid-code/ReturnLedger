"""Schema: the single source of truth for every table.

The data dictionary (docs/DATA_DICTIONARY.md), SQL DDL, CSV/JSON typing, the loader and
the enum/required/unique validation checks are all derived from the definitions below.

Internal representation: DECIMAL -> int cents, RATE -> int basis points,
DATE -> datetime.date, TIMESTAMP -> datetime.datetime, BOOLEAN -> bool, missing -> None.
"""
from dataclasses import dataclass, field
from typing import Optional

from .config import CATEGORIES, RETURN_REASONS, LOYALTY_TIERS, WAREHOUSES, CARRIERS

ENUMS = {
    "category": CATEGORIES,
    "loyalty_tier": list(LOYALTY_TIERS),
    "customer_status": ["ACTIVE", "CLOSED"],
    "order_type": ["SALE", "EXCHANGE"],
    "order_channel": ["WEB", "APP", "STORE"],
    "payment_method": ["CARD", "PAYPAL", "APPLE_PAY", "GIFT_CARD_BALANCE", "EXCHANGE_CREDIT"],
    "order_status": ["PLACED", "SHIPPED", "DELIVERED"],
    "promo_code": ["SAVE10", "FLAT15", "WELCOME5"],
    "return_channel": ["WEB", "APP", "STORE", "CALL_CENTER"],
    "resolution_type": ["REFUND", "EXCHANGE", "STORE_CREDIT"],
    "override_reason": ["LOYAL_CUSTOMER", "CARRIER_DELAY", "SERVICE_RECOVERY"],
    "rma_status": [
        "SUBMITTED", "AUTHORIZED", "PARTIALLY_AUTHORIZED", "REJECTED", "IN_TRANSIT",
        "EXPIRED", "RECEIVED", "LOST_IN_TRANSIT", "INSPECTED", "REFUNDED", "EXCHANGED",
        "CLOSED_NO_REFUND",
    ],
    "return_reason": RETURN_REASONS,
    "authorization_status": ["AUTHORIZED", "PARTIALLY_AUTHORIZED", "REJECTED"],
    "decided_by_role": ["SYSTEM_RULES", "OPS_MANAGER"],
    "line_decision": ["APPROVED", "PARTIALLY_APPROVED", "REJECTED"],
    "decision_reason": [
        "WITHIN_POLICY", "QTY_CAPPED", "REJECT_LATE", "REJECT_EXCLUDED_CATEGORY",
        "REJECT_FINAL_SALE", "REJECT_HYGIENE_OPENED", "REJECT_QTY_EXCEEDS_PURCHASED",
    ],
    "carrier": list(CARRIERS) + ["STORE_DROPOFF"],
    "warehouse_id": WAREHOUSES,
    "shipment_status": ["LABEL_CREATED", "IN_TRANSIT", "RECEIVED", "LOST", "EXPIRED"],
    "condition_grade": ["UNOPENED", "OPENED_LIKE_NEW", "DAMAGED", "DEFECTIVE", "NOT_ORIGINAL_ITEM"],
    "damage_attribution": ["NONE", "CUSTOMER", "CARRIER", "MANUFACTURER"],
    "inspection_result": ["PASS", "FAIL"],
    "refund_method": ["ORIGINAL_PAYMENT", "STORE_CREDIT"],
    "refund_status": ["REQUESTED", "PAID", "BLOCKED_DUPLICATE"],
    "disposition": ["RESTOCK", "REFURBISH", "QUARANTINE", "SCRAP"],
    "location": ["RETURNS_DOCK", "SELLABLE", "REFURB_BENCH", "QUARANTINE_CAGE", "SCRAP_BIN"],
    "entity_type": ["ORDER", "RETURN_REQUEST", "RETURN_SHIPMENT", "REFUND"],
    "actor_role": ["CUSTOMER", "SYSTEM", "OPS_MANAGER", "WAREHOUSE_OPERATOR", "CARRIER", "PAYMENT_GATEWAY"],
}

# Allowed lifecycle transitions per entity type (None = creation).
LIFECYCLES = {
    "ORDER": {None: {"PLACED"}, "PLACED": {"SHIPPED"}, "SHIPPED": {"DELIVERED"}},
    "RETURN_REQUEST": {
        None: {"SUBMITTED"},
        "SUBMITTED": {"AUTHORIZED", "PARTIALLY_AUTHORIZED", "REJECTED"},
        "AUTHORIZED": {"IN_TRANSIT", "EXPIRED"},
        "PARTIALLY_AUTHORIZED": {"IN_TRANSIT", "EXPIRED"},
        "IN_TRANSIT": {"RECEIVED", "LOST_IN_TRANSIT"},
        "RECEIVED": {"INSPECTED"},
        "INSPECTED": {"REFUNDED", "EXCHANGED", "CLOSED_NO_REFUND"},
    },
    "RETURN_SHIPMENT": {
        None: {"LABEL_CREATED"},
        "LABEL_CREATED": {"IN_TRANSIT", "EXPIRED"},
        "IN_TRANSIT": {"RECEIVED", "LOST"},
    },
    "REFUND": {None: {"REQUESTED"}, "REQUESTED": {"PAID", "BLOCKED_DUPLICATE"}},
}


@dataclass
class Field:
    name: str
    type: str  # TEXT, INTEGER, DECIMAL, RATE, DATE, TIMESTAMP, BOOLEAN
    required: bool = True
    enum: Optional[str] = None
    unit: str = ""
    unique: bool = False
    fk: Optional[str] = None  # "table.column"
    pattern: str = ""
    rule: str = ""
    desc: str = ""


@dataclass
class Table:
    name: str
    entity: str
    desc: str
    pk: list
    fields: list = field(default_factory=list)
    lifecycle: Optional[str] = None

    def col(self, name):
        return next(f for f in self.fields if f.name == name)

    @property
    def columns(self):
        return [f.name for f in self.fields]


F = Field
TS = "TIMESTAMP"
YEAR_ID = r"\d{4}-\d{6}"

TABLES = [
    Table("return_policy", "ReturnPolicy", "Effective-dated, category-specific return rules (reference data).",
          ["policy_id"], [
        F("policy_id", "TEXT", unique=True, pattern=r"POL-[A-Z_]+-V\d+", desc="Policy version id"),
        F("category", "TEXT", enum="category", desc="Product category the policy covers"),
        F("version", "INTEGER", rule=">= 1", desc="Policy version number"),
        F("effective_from", "DATE", desc="First order date the policy applies to (inclusive)"),
        F("effective_to", "DATE", required=False, rule=">= effective_from; null = open-ended",
          desc="Last order date the policy applies to (inclusive)"),
        F("return_window_days", "INTEGER", unit="days", rule="0..365",
          desc="Days after delivery a return may be requested (before loyalty extension)"),
        F("returnable", "BOOLEAN", desc="Category returnable for customer-reason returns"),
        F("opened_returnable", "BOOLEAN", desc="Opened items accepted for customer-reason returns"),
        F("restocking_fee_rate", "RATE", unit="fraction", rule="0..1",
          desc="Fee on opened, non-fault returns"),
        F("merchant_fault_override", "BOOLEAN",
          desc="Exclusions waived when the claimed reason is merchant/carrier fault"),
    ]),
    Table("customer", "Customer", "Synthetic customers (no real personal data).", ["customer_id"], [
        F("customer_id", "TEXT", unique=True, pattern=r"CUST-\d{6}"),
        F("customer_name", "TEXT", desc="Synthetic name from a fixed list of common names"),
        F("email", "TEXT", unique=True, pattern=r"user\d{6}@example\.com", desc="Reserved example.com domain"),
        F("loyalty_tier", "TEXT", enum="loyalty_tier", desc="GOLD +15 / PLATINUM +30 return-window days"),
        F("home_state", "TEXT", pattern=r"[A-Z]{2}", desc="US state code, drives sales tax"),
        F("signup_date", "DATE", rule="< first order"),
        F("customer_status", "TEXT", enum="customer_status"),
    ]),
    Table("product", "Product", "Catalogue (reference data).", ["sku"], [
        F("sku", "TEXT", unique=True, pattern=r"SKU-\d{6}"),
        F("product_name", "TEXT"),
        F("category", "TEXT", enum="category"),
        F("list_price", "DECIMAL", unit="USD", rule="> 0"),
        F("unit_cost", "DECIMAL", unit="USD", rule="> 0 and <= list_price"),
    ]),
    Table("orders", "Order", "Sales orders and zero-value exchange replacement orders.", ["order_id"], [
        F("order_id", "TEXT", unique=True, pattern=r"ORD-" + YEAR_ID),
        F("customer_id", "TEXT", fk="customer.customer_id"),
        F("order_type", "TEXT", enum="order_type"),
        F("source_rma_id", "TEXT", required=False, fk="return_request.rma_id",
          rule="required iff order_type = EXCHANGE", desc="RMA that triggered an exchange order"),
        F("order_channel", "TEXT", enum="order_channel"),
        F("placed_at", TS),
        F("shipped_at", TS, required=False, rule=">= placed_at"),
        F("delivered_at", TS, required=False, rule=">= shipped_at"),
        F("ship_state", "TEXT", pattern=r"[A-Z]{2}"),
        F("tax_rate", "RATE", unit="fraction", desc="State sales tax rate applied to taxable lines"),
        F("promo_code", "TEXT", required=False, enum="promo_code", desc="Order-level coupon"),
        F("payment_method", "TEXT", enum="payment_method"),
        F("items_subtotal", "DECIMAL", unit="USD", rule="= sum(qty * unit_price)"),
        F("line_discount_total", "DECIMAL", unit="USD", rule="= sum(line_discount)"),
        F("order_discount", "DECIMAL", unit="USD", rule="= sum(allocated_order_discount)"),
        F("shipping_fee", "DECIMAL", unit="USD", rule="0 if merchandise >= 50.00 else 5.99"),
        F("tax_total", "DECIMAL", unit="USD", rule="= sum(line tax_amount)"),
        F("order_total", "DECIMAL", unit="USD", rule="= sum(net_amount) + tax_total + shipping_fee"),
        F("current_status", "TEXT", enum="order_status", rule="= last status_event"),
    ], lifecycle="ORDER"),
    Table("order_line", "OrderLine", "Purchased items with price, discount and tax breakdown.", ["order_line_id"], [
        F("order_line_id", "TEXT", unique=True, pattern=r"ORDL-" + YEAR_ID + r"-\d{2}"),
        F("order_id", "TEXT", fk="orders.order_id"),
        F("line_no", "INTEGER", rule="1..n within order"),
        F("sku", "TEXT", fk="product.sku"),
        F("category", "TEXT", enum="category", rule="= product.category"),
        F("qty", "INTEGER", unit="units", rule=">= 1"),
        F("unit_price", "DECIMAL", unit="USD"),
        F("line_discount", "DECIMAL", unit="USD", desc="Line-level promotion / clearance markdown"),
        F("allocated_order_discount", "DECIMAL", unit="USD", desc="Pro-rata share of order coupon"),
        F("net_amount", "DECIMAL", unit="USD",
          rule="= qty*unit_price - line_discount - allocated_order_discount", desc="Paid merchandise"),
        F("tax_amount", "DECIMAL", unit="USD", rule="= round_half_up(net_amount * tax_rate); 0 if exempt"),
        F("line_total", "DECIMAL", unit="USD", rule="= net_amount + tax_amount", desc="Maximum refundable"),
        F("is_final_sale", "BOOLEAN", desc="Clearance item - not returnable unless merchant fault"),
    ]),
    Table("return_request", "ReturnRequest", "Customer return request (RMA header).", ["rma_id"], [
        F("rma_id", "TEXT", unique=True, pattern=r"RMA-" + YEAR_ID),
        F("order_id", "TEXT", fk="orders.order_id"),
        F("customer_id", "TEXT", fk="customer.customer_id", rule="= orders.customer_id"),
        F("requested_at", TS, rule=">= orders.delivered_at"),
        F("return_channel", "TEXT", enum="return_channel"),
        F("resolution_type", "TEXT", enum="resolution_type", desc="What the customer asked for"),
        F("late_override_flag", "BOOLEAN", desc="Ops manager approved a late return"),
        F("override_by", "TEXT", required=False, pattern=r"OPS-\d{3}", rule="required iff override"),
        F("override_reason", "TEXT", required=False, enum="override_reason", rule="required iff override"),
        F("current_status", "TEXT", enum="rma_status", rule="= last status_event"),
    ], lifecycle="RETURN_REQUEST"),
    Table("return_line", "ReturnLine", "Items and quantities the customer asks to return.", ["return_line_id"], [
        F("return_line_id", "TEXT", unique=True, pattern=r"RMAL-RMA-" + YEAR_ID + r"-\d{2}"),
        F("rma_id", "TEXT", fk="return_request.rma_id"),
        F("order_line_id", "TEXT", fk="order_line.order_line_id", rule="order_line.order_id = rma.order_id"),
        F("sku", "TEXT", fk="product.sku", rule="= order_line.sku"),
        F("requested_qty", "INTEGER", unit="units", rule=">= 1 (may exceed purchased: exception path)"),
        F("return_reason", "TEXT", enum="return_reason"),
        F("item_opened", "BOOLEAN", desc="Customer-declared packaging opened"),
    ]),
    Table("return_authorization", "ReturnAuthorization", "Eligibility decision for an RMA (0..1 per RMA).",
          ["authorization_id"], [
        F("authorization_id", "TEXT", unique=True, pattern=r"RA-" + YEAR_ID),
        F("rma_id", "TEXT", unique=True, fk="return_request.rma_id"),
        F("decided_at", TS, rule=">= requested_at"),
        F("decided_by_role", "TEXT", enum="decided_by_role"),
        F("decision_status", "TEXT", enum="authorization_status", rule="derived from line decisions"),
        F("approved_qty_total", "INTEGER", unit="units", rule="= sum(authorization_line.approved_qty)"),
        F("label_expires_at", TS, required=False, rule="decided_at + 14 days if any approved"),
    ]),
    Table("authorization_line", "AuthorizationLine", "Line-level decision (1:1 with return_line).",
          ["authorization_line_id"], [
        F("authorization_line_id", "TEXT", unique=True, pattern=r"RAL-RMA-" + YEAR_ID + r"-\d{2}"),
        F("authorization_id", "TEXT", fk="return_authorization.authorization_id"),
        F("return_line_id", "TEXT", unique=True, fk="return_line.return_line_id"),
        F("policy_id", "TEXT", fk="return_policy.policy_id", desc="Policy version applied"),
        F("days_since_delivery", "INTEGER", unit="days"),
        F("effective_window_days", "INTEGER", unit="days", desc="Policy window + loyalty extension"),
        F("prior_approved_qty", "INTEGER", unit="units", desc="Approved on earlier RMAs for this order line"),
        F("approved_qty", "INTEGER", unit="units", rule="<= requested_qty and <= qty - prior_approved_qty"),
        F("line_decision", "TEXT", enum="line_decision"),
        F("decision_reason", "TEXT", enum="decision_reason"),
        F("override_applied", "BOOLEAN", desc="Late, but approved via manager override"),
    ]),
    Table("return_shipment", "ReturnShipment", "Return label / parcel (1..N per authorized RMA).", ["shipment_id"], [
        F("shipment_id", "TEXT", unique=True, pattern=r"RTS-" + YEAR_ID),
        F("rma_id", "TEXT", fk="return_request.rma_id"),
        F("authorization_id", "TEXT", fk="return_authorization.authorization_id"),
        F("carrier", "TEXT", enum="carrier"),
        F("tracking_number", "TEXT", unique=True),
        F("warehouse_id", "TEXT", enum="warehouse_id"),
        F("label_created_at", TS, rule=">= authorization.decided_at"),
        F("shipped_at", TS, required=False, rule=">= label_created_at and <= label_expires_at"),
        F("received_at", TS, required=False, rule=">= shipped_at"),
        F("current_status", "TEXT", enum="shipment_status", rule="= last status_event"),
    ], lifecycle="RETURN_SHIPMENT"),
    Table("shipment_line", "ShipmentLine", "Bridge: return_shipment N:M return_line (split shipments).",
          ["shipment_id", "return_line_id"], [
        F("shipment_id", "TEXT", fk="return_shipment.shipment_id"),
        F("return_line_id", "TEXT", fk="return_line.return_line_id"),
        F("shipped_qty", "INTEGER", unit="units", rule=">= 1; sum per line <= approved_qty"),
    ]),
    Table("inspection", "Inspection", "Warehouse inspection of a received shipment line.", ["inspection_id"], [
        F("inspection_id", "TEXT", unique=True, pattern=r"INS-" + YEAR_ID),
        F("shipment_id", "TEXT", fk="return_shipment.shipment_id"),
        F("return_line_id", "TEXT", fk="return_line.return_line_id"),
        F("inspector_id", "TEXT", pattern=r"OPS-\d{3}"),
        F("inspected_at", TS, rule=">= shipment.received_at"),
        F("received_qty", "INTEGER", unit="units", rule="0..shipped_qty"),
        F("condition_grade", "TEXT", enum="condition_grade"),
        F("damage_attribution", "TEXT", enum="damage_attribution"),
        F("inspection_result", "TEXT", enum="inspection_result",
          rule="FAIL if customer damage, not original item, or short-shipped"),
    ]),
    Table("refund", "Refund", "Refund payout attempt (idempotent per RMA).", ["refund_id"], [
        F("refund_id", "TEXT", unique=True, pattern=r"REF-" + YEAR_ID),
        F("rma_id", "TEXT", fk="return_request.rma_id"),
        F("idempotency_key", "TEXT", desc="<rma_id>:REFUND:<n>; repeats are blocked"),
        F("attempt_seq", "INTEGER", rule=">= 1"),
        F("refund_method", "TEXT", enum="refund_method"),
        F("requested_at", TS, rule=">= last inspection"),
        F("processed_at", TS, required=False, rule=">= requested_at"),
        F("lines_amount", "DECIMAL", unit="USD", rule="= sum(refund_line.line_refund_amount)"),
        F("shipping_refund", "DECIMAL", unit="USD", desc="Original shipping, if merchant fault"),
        F("return_label_fee", "DECIMAL", unit="USD", desc="Deducted for customer-reason mail returns"),
        F("refund_amount", "DECIMAL", unit="USD", rule="= lines_amount + shipping_refund - return_label_fee"),
        F("paid_amount", "DECIMAL", unit="USD", rule="= refund_amount if PAID else 0"),
        F("current_status", "TEXT", enum="refund_status", rule="= last status_event"),
        F("blocked_reason", "TEXT", required=False),
    ], lifecycle="REFUND"),
    Table("refund_line", "RefundLine", "Refund calculation per inspected line.", ["refund_line_id"], [
        F("refund_line_id", "TEXT", unique=True, pattern=r"REFL-REF-" + YEAR_ID + r"-\d{2}"),
        F("refund_id", "TEXT", fk="refund.refund_id"),
        F("return_line_id", "TEXT", fk="return_line.return_line_id"),
        F("inspection_id", "TEXT", fk="inspection.inspection_id"),
        F("order_line_id", "TEXT", fk="order_line.order_line_id"),
        F("refund_qty", "INTEGER", unit="units", rule="= inspection.received_qty"),
        F("merchandise_amount", "DECIMAL", unit="USD", rule="= round_half_up(net_amount * refund_qty / qty)"),
        F("tax_amount", "DECIMAL", unit="USD", rule="= round_half_up(line tax * refund_qty / qty)"),
        F("restocking_fee", "DECIMAL", unit="USD", rule="merchandise * fee rate if opened & not merchant fault"),
        F("damage_deduction", "DECIMAL", unit="USD", rule="50% merchandise if customer damage"),
        F("cap_adjustment", "DECIMAL", unit="USD", rule="reduces refund to remaining refundable"),
        F("line_refund_amount", "DECIMAL", unit="USD",
          rule="= merchandise + tax - restocking_fee - damage_deduction - cap_adjustment"),
    ]),
    Table("inventory_disposition", "InventoryDisposition", "Decision on what happens to returned units.",
          ["disposition_id"], [
        F("disposition_id", "TEXT", unique=True, pattern=r"DISP-" + YEAR_ID),
        F("inspection_id", "TEXT", unique=True, fk="inspection.inspection_id"),
        F("return_line_id", "TEXT", fk="return_line.return_line_id"),
        F("sku", "TEXT", fk="product.sku"),
        F("qty", "INTEGER", unit="units", rule="= inspection.received_qty"),
        F("disposition", "TEXT", enum="disposition"),
        F("decided_at", TS, rule=">= inspection.inspected_at"),
        F("decided_by", "TEXT", pattern=r"OPS-\d{3}"),
    ]),
    Table("inventory_movement", "InventoryMovement", "Stock movement produced by a disposition.", ["movement_id"], [
        F("movement_id", "TEXT", unique=True, pattern=r"IMV-" + YEAR_ID),
        F("disposition_id", "TEXT", unique=True, fk="inventory_disposition.disposition_id"),
        F("sku", "TEXT", fk="product.sku"),
        F("warehouse_id", "TEXT", enum="warehouse_id"),
        F("from_location", "TEXT", enum="location"),
        F("to_location", "TEXT", enum="location", rule="determined by disposition"),
        F("qty", "INTEGER", unit="units"),
        F("unit_cost", "DECIMAL", unit="USD"),
        F("movement_value", "DECIMAL", unit="USD", rule="= qty * unit_cost"),
        F("moved_at", TS, rule="= disposition.decided_at"),
    ]),
    Table("status_event", "StatusEvent", "Append-only lifecycle history for orders, RMAs, shipments, refunds.",
          ["event_id"], [
        F("event_id", "TEXT", unique=True, pattern=r"EVT-\d{4}-\d{7}"),
        F("entity_type", "TEXT", enum="entity_type"),
        F("entity_id", "TEXT", desc="Polymorphic reference, validated per entity_type"),
        F("from_status", "TEXT", required=False, desc="null for the creation event"),
        F("to_status", "TEXT", rule="allowed transition from from_status"),
        F("event_ts", TS, rule="non-decreasing per entity"),
        F("actor_role", "TEXT", enum="actor_role"),
        F("actor_id", "TEXT", required=False),
        F("reason_code", "TEXT", required=False),
    ]),
]

TABLE_BY_NAME = {t.name: t for t in TABLES}

# Relationships with cardinality for documentation (parent, child, cardinality, optionality).
RELATIONSHIPS = [
    ("customer", "orders", "1:N", "customer has 0..N orders"),
    ("orders", "order_line", "1:N", "order has 1..N lines"),
    ("product", "order_line", "1:N", "product appears on 0..N lines"),
    ("return_policy", "authorization_line", "1:N", "policy version applied to 0..N decisions"),
    ("orders", "return_request", "1:N", "order has 0..N RMAs (repeat/partial returns)"),
    ("customer", "return_request", "1:N", "customer raises 0..N RMAs"),
    ("return_request", "return_line", "1:N", "RMA has 1..N lines"),
    ("order_line", "return_line", "1:N", "order line returned on 0..N RMAs"),
    ("return_request", "return_authorization", "1:0..1", "RMA decided at most once (pending = none)"),
    ("return_authorization", "authorization_line", "1:N", "one decision per return line"),
    ("return_line", "authorization_line", "1:0..1", "line decision"),
    ("return_authorization", "return_shipment", "1:0..N", "authorized RMAs get 1..N labels"),
    ("return_shipment", "return_line", "N:M", "bridge shipment_line (split shipments)"),
    ("shipment_line", "inspection", "1:0..1", "received shipment line inspected once"),
    ("return_request", "refund", "1:0..N", "payout attempts; only one may be PAID"),
    ("refund", "refund_line", "1:N", "per inspected line"),
    ("inspection", "inventory_disposition", "1:0..1", "units received get a disposition"),
    ("inventory_disposition", "inventory_movement", "1:1", "disposition moves stock"),
    ("return_request", "orders(EXCHANGE)", "1:0..1", "exchange replacement order"),
    ("orders/return_request/return_shipment/refund", "status_event", "1:N", "append-only history"),
]
