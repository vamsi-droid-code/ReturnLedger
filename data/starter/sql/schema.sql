-- ReturnLedger schema (generated from returnledger/schema.py). ANSI-style SQL; tested on SQLite.
-- Foreign keys are DEFERRABLE so the exchange-order <-> RMA cycle can be loaded in one transaction.

-- ReturnPolicy: Effective-dated, category-specific return rules (reference data).
CREATE TABLE return_policy (
    policy_id TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('APPAREL', 'ELECTRONICS', 'HOME', 'BEAUTY', 'GROCERY', 'TOYS', 'SPORTS', 'BOOKS', 'JEWELRY', 'GIFT_CARD')),
    version INTEGER NOT NULL,
    effective_from DATE NOT NULL,
    effective_to DATE,
    return_window_days INTEGER NOT NULL,
    returnable BOOLEAN NOT NULL,
    opened_returnable BOOLEAN NOT NULL,
    restocking_fee_rate NUMERIC(6,4) NOT NULL,
    merchant_fault_override BOOLEAN NOT NULL,
    PRIMARY KEY (policy_id)
);

-- Customer: Synthetic customers (no real personal data).
CREATE TABLE customer (
    customer_id TEXT NOT NULL,
    customer_name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    loyalty_tier TEXT NOT NULL CHECK (loyalty_tier IN ('STANDARD', 'SILVER', 'GOLD', 'PLATINUM')),
    home_state TEXT NOT NULL,
    signup_date DATE NOT NULL,
    customer_status TEXT NOT NULL CHECK (customer_status IN ('ACTIVE', 'CLOSED')),
    PRIMARY KEY (customer_id)
);

-- Product: Catalogue (reference data).
CREATE TABLE product (
    sku TEXT NOT NULL,
    product_name TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('APPAREL', 'ELECTRONICS', 'HOME', 'BEAUTY', 'GROCERY', 'TOYS', 'SPORTS', 'BOOKS', 'JEWELRY', 'GIFT_CARD')),
    list_price NUMERIC(12,2) NOT NULL,
    unit_cost NUMERIC(12,2) NOT NULL,
    PRIMARY KEY (sku)
);

-- Order: Sales orders and zero-value exchange replacement orders.
CREATE TABLE orders (
    order_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    order_type TEXT NOT NULL CHECK (order_type IN ('SALE', 'EXCHANGE')),
    source_rma_id TEXT,
    order_channel TEXT NOT NULL CHECK (order_channel IN ('WEB', 'APP', 'STORE')),
    placed_at TIMESTAMP NOT NULL,
    shipped_at TIMESTAMP,
    delivered_at TIMESTAMP,
    ship_state TEXT NOT NULL,
    tax_rate NUMERIC(6,4) NOT NULL,
    promo_code TEXT CHECK (promo_code IN ('SAVE10', 'FLAT15', 'WELCOME5')),
    payment_method TEXT NOT NULL CHECK (payment_method IN ('CARD', 'PAYPAL', 'APPLE_PAY', 'GIFT_CARD_BALANCE', 'EXCHANGE_CREDIT')),
    items_subtotal NUMERIC(12,2) NOT NULL,
    line_discount_total NUMERIC(12,2) NOT NULL,
    order_discount NUMERIC(12,2) NOT NULL,
    shipping_fee NUMERIC(12,2) NOT NULL,
    tax_total NUMERIC(12,2) NOT NULL,
    order_total NUMERIC(12,2) NOT NULL,
    current_status TEXT NOT NULL CHECK (current_status IN ('PLACED', 'SHIPPED', 'DELIVERED')),
    PRIMARY KEY (order_id),
    FOREIGN KEY (customer_id) REFERENCES customer (customer_id) DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (source_rma_id) REFERENCES return_request (rma_id) DEFERRABLE INITIALLY DEFERRED
);

-- OrderLine: Purchased items with price, discount and tax breakdown.
CREATE TABLE order_line (
    order_line_id TEXT NOT NULL,
    order_id TEXT NOT NULL,
    line_no INTEGER NOT NULL,
    sku TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('APPAREL', 'ELECTRONICS', 'HOME', 'BEAUTY', 'GROCERY', 'TOYS', 'SPORTS', 'BOOKS', 'JEWELRY', 'GIFT_CARD')),
    qty INTEGER NOT NULL,
    unit_price NUMERIC(12,2) NOT NULL,
    line_discount NUMERIC(12,2) NOT NULL,
    allocated_order_discount NUMERIC(12,2) NOT NULL,
    net_amount NUMERIC(12,2) NOT NULL,
    tax_amount NUMERIC(12,2) NOT NULL,
    line_total NUMERIC(12,2) NOT NULL,
    is_final_sale BOOLEAN NOT NULL,
    PRIMARY KEY (order_line_id),
    FOREIGN KEY (order_id) REFERENCES orders (order_id) DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (sku) REFERENCES product (sku) DEFERRABLE INITIALLY DEFERRED
);

-- ReturnRequest: Customer return request (RMA header).
CREATE TABLE return_request (
    rma_id TEXT NOT NULL,
    order_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    requested_at TIMESTAMP NOT NULL,
    return_channel TEXT NOT NULL CHECK (return_channel IN ('WEB', 'APP', 'STORE', 'CALL_CENTER')),
    resolution_type TEXT NOT NULL CHECK (resolution_type IN ('REFUND', 'EXCHANGE', 'STORE_CREDIT')),
    late_override_flag BOOLEAN NOT NULL,
    override_by TEXT,
    override_reason TEXT CHECK (override_reason IN ('LOYAL_CUSTOMER', 'CARRIER_DELAY', 'SERVICE_RECOVERY')),
    current_status TEXT NOT NULL CHECK (current_status IN ('SUBMITTED', 'AUTHORIZED', 'PARTIALLY_AUTHORIZED', 'REJECTED', 'IN_TRANSIT', 'EXPIRED', 'RECEIVED', 'LOST_IN_TRANSIT', 'INSPECTED', 'REFUNDED', 'EXCHANGED', 'CLOSED_NO_REFUND')),
    PRIMARY KEY (rma_id),
    FOREIGN KEY (order_id) REFERENCES orders (order_id) DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (customer_id) REFERENCES customer (customer_id) DEFERRABLE INITIALLY DEFERRED
);

-- ReturnLine: Items and quantities the customer asks to return.
CREATE TABLE return_line (
    return_line_id TEXT NOT NULL,
    rma_id TEXT NOT NULL,
    order_line_id TEXT NOT NULL,
    sku TEXT NOT NULL,
    requested_qty INTEGER NOT NULL,
    return_reason TEXT NOT NULL CHECK (return_reason IN ('CHANGED_MIND', 'WRONG_SIZE', 'NOT_AS_DESCRIBED', 'DEFECTIVE', 'DAMAGED_IN_TRANSIT', 'WRONG_ITEM')),
    item_opened BOOLEAN NOT NULL,
    PRIMARY KEY (return_line_id),
    FOREIGN KEY (rma_id) REFERENCES return_request (rma_id) DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (order_line_id) REFERENCES order_line (order_line_id) DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (sku) REFERENCES product (sku) DEFERRABLE INITIALLY DEFERRED
);

-- ReturnAuthorization: Eligibility decision for an RMA (0..1 per RMA).
CREATE TABLE return_authorization (
    authorization_id TEXT NOT NULL,
    rma_id TEXT NOT NULL UNIQUE,
    decided_at TIMESTAMP NOT NULL,
    decided_by_role TEXT NOT NULL CHECK (decided_by_role IN ('SYSTEM_RULES', 'OPS_MANAGER')),
    decision_status TEXT NOT NULL CHECK (decision_status IN ('AUTHORIZED', 'PARTIALLY_AUTHORIZED', 'REJECTED')),
    approved_qty_total INTEGER NOT NULL,
    label_expires_at TIMESTAMP,
    PRIMARY KEY (authorization_id),
    FOREIGN KEY (rma_id) REFERENCES return_request (rma_id) DEFERRABLE INITIALLY DEFERRED
);

-- AuthorizationLine: Line-level decision (1:1 with return_line).
CREATE TABLE authorization_line (
    authorization_line_id TEXT NOT NULL,
    authorization_id TEXT NOT NULL,
    return_line_id TEXT NOT NULL UNIQUE,
    policy_id TEXT NOT NULL,
    days_since_delivery INTEGER NOT NULL,
    effective_window_days INTEGER NOT NULL,
    prior_approved_qty INTEGER NOT NULL,
    approved_qty INTEGER NOT NULL,
    line_decision TEXT NOT NULL CHECK (line_decision IN ('APPROVED', 'PARTIALLY_APPROVED', 'REJECTED')),
    decision_reason TEXT NOT NULL CHECK (decision_reason IN ('WITHIN_POLICY', 'QTY_CAPPED', 'REJECT_LATE', 'REJECT_EXCLUDED_CATEGORY', 'REJECT_FINAL_SALE', 'REJECT_HYGIENE_OPENED', 'REJECT_QTY_EXCEEDS_PURCHASED')),
    override_applied BOOLEAN NOT NULL,
    PRIMARY KEY (authorization_line_id),
    FOREIGN KEY (authorization_id) REFERENCES return_authorization (authorization_id) DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (return_line_id) REFERENCES return_line (return_line_id) DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (policy_id) REFERENCES return_policy (policy_id) DEFERRABLE INITIALLY DEFERRED
);

-- ReturnShipment: Return label / parcel (1..N per authorized RMA).
CREATE TABLE return_shipment (
    shipment_id TEXT NOT NULL,
    rma_id TEXT NOT NULL,
    authorization_id TEXT NOT NULL,
    carrier TEXT NOT NULL CHECK (carrier IN ('UPS', 'FEDEX', 'USPS', 'DHL', 'STORE_DROPOFF')),
    tracking_number TEXT NOT NULL UNIQUE,
    warehouse_id TEXT NOT NULL CHECK (warehouse_id IN ('WH-01', 'WH-02', 'WH-03', 'WH-04')),
    label_created_at TIMESTAMP NOT NULL,
    shipped_at TIMESTAMP,
    received_at TIMESTAMP,
    current_status TEXT NOT NULL CHECK (current_status IN ('LABEL_CREATED', 'IN_TRANSIT', 'RECEIVED', 'LOST', 'EXPIRED')),
    PRIMARY KEY (shipment_id),
    FOREIGN KEY (rma_id) REFERENCES return_request (rma_id) DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (authorization_id) REFERENCES return_authorization (authorization_id) DEFERRABLE INITIALLY DEFERRED
);

-- ShipmentLine: Bridge: return_shipment N:M return_line (split shipments).
CREATE TABLE shipment_line (
    shipment_id TEXT NOT NULL,
    return_line_id TEXT NOT NULL,
    shipped_qty INTEGER NOT NULL,
    PRIMARY KEY (shipment_id, return_line_id),
    FOREIGN KEY (shipment_id) REFERENCES return_shipment (shipment_id) DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (return_line_id) REFERENCES return_line (return_line_id) DEFERRABLE INITIALLY DEFERRED
);

-- Inspection: Warehouse inspection of a received shipment line.
CREATE TABLE inspection (
    inspection_id TEXT NOT NULL,
    shipment_id TEXT NOT NULL,
    return_line_id TEXT NOT NULL,
    inspector_id TEXT NOT NULL,
    inspected_at TIMESTAMP NOT NULL,
    received_qty INTEGER NOT NULL,
    condition_grade TEXT NOT NULL CHECK (condition_grade IN ('UNOPENED', 'OPENED_LIKE_NEW', 'DAMAGED', 'DEFECTIVE', 'NOT_ORIGINAL_ITEM')),
    damage_attribution TEXT NOT NULL CHECK (damage_attribution IN ('NONE', 'CUSTOMER', 'CARRIER', 'MANUFACTURER')),
    inspection_result TEXT NOT NULL CHECK (inspection_result IN ('PASS', 'FAIL')),
    PRIMARY KEY (inspection_id),
    FOREIGN KEY (shipment_id) REFERENCES return_shipment (shipment_id) DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (return_line_id) REFERENCES return_line (return_line_id) DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (shipment_id, return_line_id) REFERENCES shipment_line (shipment_id, return_line_id) DEFERRABLE INITIALLY DEFERRED
);

-- Refund: Refund payout attempt (idempotent per RMA).
CREATE TABLE refund (
    refund_id TEXT NOT NULL,
    rma_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    attempt_seq INTEGER NOT NULL,
    refund_method TEXT NOT NULL CHECK (refund_method IN ('ORIGINAL_PAYMENT', 'STORE_CREDIT')),
    requested_at TIMESTAMP NOT NULL,
    processed_at TIMESTAMP,
    lines_amount NUMERIC(12,2) NOT NULL,
    shipping_refund NUMERIC(12,2) NOT NULL,
    return_label_fee NUMERIC(12,2) NOT NULL,
    refund_amount NUMERIC(12,2) NOT NULL,
    paid_amount NUMERIC(12,2) NOT NULL,
    current_status TEXT NOT NULL CHECK (current_status IN ('REQUESTED', 'PAID', 'BLOCKED_DUPLICATE')),
    blocked_reason TEXT,
    PRIMARY KEY (refund_id),
    FOREIGN KEY (rma_id) REFERENCES return_request (rma_id) DEFERRABLE INITIALLY DEFERRED
);

-- RefundLine: Refund calculation per inspected line.
CREATE TABLE refund_line (
    refund_line_id TEXT NOT NULL,
    refund_id TEXT NOT NULL,
    return_line_id TEXT NOT NULL,
    inspection_id TEXT NOT NULL,
    order_line_id TEXT NOT NULL,
    refund_qty INTEGER NOT NULL,
    merchandise_amount NUMERIC(12,2) NOT NULL,
    tax_amount NUMERIC(12,2) NOT NULL,
    restocking_fee NUMERIC(12,2) NOT NULL,
    damage_deduction NUMERIC(12,2) NOT NULL,
    cap_adjustment NUMERIC(12,2) NOT NULL,
    line_refund_amount NUMERIC(12,2) NOT NULL,
    PRIMARY KEY (refund_line_id),
    FOREIGN KEY (refund_id) REFERENCES refund (refund_id) DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (return_line_id) REFERENCES return_line (return_line_id) DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (inspection_id) REFERENCES inspection (inspection_id) DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (order_line_id) REFERENCES order_line (order_line_id) DEFERRABLE INITIALLY DEFERRED
);

-- InventoryDisposition: Decision on what happens to returned units.
CREATE TABLE inventory_disposition (
    disposition_id TEXT NOT NULL,
    inspection_id TEXT NOT NULL UNIQUE,
    return_line_id TEXT NOT NULL,
    sku TEXT NOT NULL,
    qty INTEGER NOT NULL,
    disposition TEXT NOT NULL CHECK (disposition IN ('RESTOCK', 'REFURBISH', 'QUARANTINE', 'SCRAP')),
    decided_at TIMESTAMP NOT NULL,
    decided_by TEXT NOT NULL,
    PRIMARY KEY (disposition_id),
    FOREIGN KEY (inspection_id) REFERENCES inspection (inspection_id) DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (return_line_id) REFERENCES return_line (return_line_id) DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (sku) REFERENCES product (sku) DEFERRABLE INITIALLY DEFERRED
);

-- InventoryMovement: Stock movement produced by a disposition.
CREATE TABLE inventory_movement (
    movement_id TEXT NOT NULL,
    disposition_id TEXT NOT NULL UNIQUE,
    sku TEXT NOT NULL,
    warehouse_id TEXT NOT NULL CHECK (warehouse_id IN ('WH-01', 'WH-02', 'WH-03', 'WH-04')),
    from_location TEXT NOT NULL CHECK (from_location IN ('RETURNS_DOCK', 'SELLABLE', 'REFURB_BENCH', 'QUARANTINE_CAGE', 'SCRAP_BIN')),
    to_location TEXT NOT NULL CHECK (to_location IN ('RETURNS_DOCK', 'SELLABLE', 'REFURB_BENCH', 'QUARANTINE_CAGE', 'SCRAP_BIN')),
    qty INTEGER NOT NULL,
    unit_cost NUMERIC(12,2) NOT NULL,
    movement_value NUMERIC(12,2) NOT NULL,
    moved_at TIMESTAMP NOT NULL,
    PRIMARY KEY (movement_id),
    FOREIGN KEY (disposition_id) REFERENCES inventory_disposition (disposition_id) DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (sku) REFERENCES product (sku) DEFERRABLE INITIALLY DEFERRED
);

-- StatusEvent: Append-only lifecycle history for orders, RMAs, shipments, refunds.
CREATE TABLE status_event (
    event_id TEXT NOT NULL,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('ORDER', 'RETURN_REQUEST', 'RETURN_SHIPMENT', 'REFUND')),
    entity_id TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT NOT NULL,
    event_ts TIMESTAMP NOT NULL,
    actor_role TEXT NOT NULL CHECK (actor_role IN ('CUSTOMER', 'SYSTEM', 'OPS_MANAGER', 'WAREHOUSE_OPERATOR', 'CARRIER', 'PAYMENT_GATEWAY')),
    actor_id TEXT,
    reason_code TEXT,
    PRIMARY KEY (event_id)
);
