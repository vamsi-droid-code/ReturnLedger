# Data dictionary

Generated from `returnledger/schema.py` (`python -m returnledger docs`). Money columns are USD with 2 decimals (stored internally as integer cents); rates are fractions with 4 decimals; timestamps are ISO-8601 local time without zone; booleans are `true`/`false`; empty = null.

## Relationships and cardinality

| Parent | Child | Cardinality | Meaning |
|---|---|---|---|
| customer | orders | 1:N | customer has 0..N orders |
| orders | order_line | 1:N | order has 1..N lines |
| product | order_line | 1:N | product appears on 0..N lines |
| return_policy | authorization_line | 1:N | policy version applied to 0..N decisions |
| orders | return_request | 1:N | order has 0..N RMAs (repeat/partial returns) |
| customer | return_request | 1:N | customer raises 0..N RMAs |
| return_request | return_line | 1:N | RMA has 1..N lines |
| order_line | return_line | 1:N | order line returned on 0..N RMAs |
| return_request | return_authorization | 1:0..1 | RMA decided at most once (pending = none) |
| return_authorization | authorization_line | 1:N | one decision per return line |
| return_line | authorization_line | 1:0..1 | line decision |
| return_authorization | return_shipment | 1:0..N | authorized RMAs get 1..N labels |
| return_shipment | return_line | N:M | bridge shipment_line (split shipments) |
| shipment_line | inspection | 1:0..1 | received shipment line inspected once |
| return_request | refund | 1:0..N | payout attempts; only one may be PAID |
| refund | refund_line | 1:N | per inspected line |
| inspection | inventory_disposition | 1:0..1 | units received get a disposition |
| inventory_disposition | inventory_movement | 1:1 | disposition moves stock |
| return_request | orders(EXCHANGE) | 1:0..1 | exchange replacement order |
| orders/return_request/return_shipment/refund | status_event | 1:N | append-only history |

## Lifecycles (allowed transitions, recorded in `status_event`)

- **ORDER**: (create) -> PLACED; PLACED -> SHIPPED; SHIPPED -> DELIVERED
- **RETURN_REQUEST**: (create) -> SUBMITTED; SUBMITTED -> AUTHORIZED/PARTIALLY_AUTHORIZED/REJECTED; AUTHORIZED -> EXPIRED/IN_TRANSIT; PARTIALLY_AUTHORIZED -> EXPIRED/IN_TRANSIT; IN_TRANSIT -> LOST_IN_TRANSIT/RECEIVED; RECEIVED -> INSPECTED; INSPECTED -> CLOSED_NO_REFUND/EXCHANGED/REFUNDED
- **RETURN_SHIPMENT**: (create) -> LABEL_CREATED; LABEL_CREATED -> EXPIRED/IN_TRANSIT; IN_TRANSIT -> LOST/RECEIVED
- **REFUND**: (create) -> REQUESTED; REQUESTED -> BLOCKED_DUPLICATE/PAID

## `return_policy` (ReturnPolicy)

Effective-dated, category-specific return rules (reference data).

Primary key: `policy_id`

| Field | Type | Required | Allowed values / format | Unit | Unique | FK | Validation rule | Description |
|---|---|---|---|---|---|---|---|---|
| `policy_id` | TEXT | yes | `POL-[A-Z_]+-V\d+` |  | yes |  |  | Policy version id |
| `category` | TEXT | yes | APPAREL, ELECTRONICS, HOME, BEAUTY, GROCERY, TOYS, SPORTS, BOOKS, JEWELRY, GIFT_CARD |  |  |  |  | Product category the policy covers |
| `version` | INTEGER | yes |  |  |  |  | >= 1 | Policy version number |
| `effective_from` | DATE | yes |  |  |  |  |  | First order date the policy applies to (inclusive) |
| `effective_to` | DATE | no |  |  |  |  | >= effective_from; null = open-ended | Last order date the policy applies to (inclusive) |
| `return_window_days` | INTEGER | yes |  | days |  |  | 0..365 | Days after delivery a return may be requested (before loyalty extension) |
| `returnable` | BOOLEAN | yes |  |  |  |  |  | Category returnable for customer-reason returns |
| `opened_returnable` | BOOLEAN | yes |  |  |  |  |  | Opened items accepted for customer-reason returns |
| `restocking_fee_rate` | RATE | yes |  | fraction |  |  | 0..1 | Fee on opened, non-fault returns |
| `merchant_fault_override` | BOOLEAN | yes |  |  |  |  |  | Exclusions waived when the claimed reason is merchant/carrier fault |

## `customer` (Customer)

Synthetic customers (no real personal data).

Primary key: `customer_id`

| Field | Type | Required | Allowed values / format | Unit | Unique | FK | Validation rule | Description |
|---|---|---|---|---|---|---|---|---|
| `customer_id` | TEXT | yes | `CUST-\d{6}` |  | yes |  |  |  |
| `customer_name` | TEXT | yes |  |  |  |  |  | Synthetic name from a fixed list of common names |
| `email` | TEXT | yes | `user\d{6}@example\.com` |  | yes |  |  | Reserved example.com domain |
| `loyalty_tier` | TEXT | yes | STANDARD, SILVER, GOLD, PLATINUM |  |  |  |  | GOLD +15 / PLATINUM +30 return-window days |
| `home_state` | TEXT | yes | `[A-Z]{2}` |  |  |  |  | US state code, drives sales tax |
| `signup_date` | DATE | yes |  |  |  |  | < first order |  |
| `customer_status` | TEXT | yes | ACTIVE, CLOSED |  |  |  |  |  |

## `product` (Product)

Catalogue (reference data).

Primary key: `sku`

| Field | Type | Required | Allowed values / format | Unit | Unique | FK | Validation rule | Description |
|---|---|---|---|---|---|---|---|---|
| `sku` | TEXT | yes | `SKU-\d{6}` |  | yes |  |  |  |
| `product_name` | TEXT | yes |  |  |  |  |  |  |
| `category` | TEXT | yes | APPAREL, ELECTRONICS, HOME, BEAUTY, GROCERY, TOYS, SPORTS, BOOKS, JEWELRY, GIFT_CARD |  |  |  |  |  |
| `list_price` | DECIMAL | yes |  | USD |  |  | > 0 |  |
| `unit_cost` | DECIMAL | yes |  | USD |  |  | > 0 and <= list_price |  |

## `orders` (Order)

Sales orders and zero-value exchange replacement orders.

Primary key: `order_id`

| Field | Type | Required | Allowed values / format | Unit | Unique | FK | Validation rule | Description |
|---|---|---|---|---|---|---|---|---|
| `order_id` | TEXT | yes | `ORD-\d{4}-\d{6}` |  | yes |  |  |  |
| `customer_id` | TEXT | yes |  |  |  | customer.customer_id |  |  |
| `order_type` | TEXT | yes | SALE, EXCHANGE |  |  |  |  |  |
| `source_rma_id` | TEXT | no |  |  |  | return_request.rma_id | required iff order_type = EXCHANGE | RMA that triggered an exchange order |
| `order_channel` | TEXT | yes | WEB, APP, STORE |  |  |  |  |  |
| `placed_at` | TIMESTAMP | yes |  |  |  |  |  |  |
| `shipped_at` | TIMESTAMP | no |  |  |  |  | >= placed_at |  |
| `delivered_at` | TIMESTAMP | no |  |  |  |  | >= shipped_at |  |
| `ship_state` | TEXT | yes | `[A-Z]{2}` |  |  |  |  |  |
| `tax_rate` | RATE | yes |  | fraction |  |  |  | State sales tax rate applied to taxable lines |
| `promo_code` | TEXT | no | SAVE10, FLAT15, WELCOME5 |  |  |  |  | Order-level coupon |
| `payment_method` | TEXT | yes | CARD, PAYPAL, APPLE_PAY, GIFT_CARD_BALANCE, EXCHANGE_CREDIT |  |  |  |  |  |
| `items_subtotal` | DECIMAL | yes |  | USD |  |  | = sum(qty * unit_price) |  |
| `line_discount_total` | DECIMAL | yes |  | USD |  |  | = sum(line_discount) |  |
| `order_discount` | DECIMAL | yes |  | USD |  |  | = sum(allocated_order_discount) |  |
| `shipping_fee` | DECIMAL | yes |  | USD |  |  | 0 if merchandise >= 50.00 else 5.99 |  |
| `tax_total` | DECIMAL | yes |  | USD |  |  | = sum(line tax_amount) |  |
| `order_total` | DECIMAL | yes |  | USD |  |  | = sum(net_amount) + tax_total + shipping_fee |  |
| `current_status` | TEXT | yes | PLACED, SHIPPED, DELIVERED |  |  |  | = last status_event |  |

## `order_line` (OrderLine)

Purchased items with price, discount and tax breakdown.

Primary key: `order_line_id`

| Field | Type | Required | Allowed values / format | Unit | Unique | FK | Validation rule | Description |
|---|---|---|---|---|---|---|---|---|
| `order_line_id` | TEXT | yes | `ORDL-\d{4}-\d{6}-\d{2}` |  | yes |  |  |  |
| `order_id` | TEXT | yes |  |  |  | orders.order_id |  |  |
| `line_no` | INTEGER | yes |  |  |  |  | 1..n within order |  |
| `sku` | TEXT | yes |  |  |  | product.sku |  |  |
| `category` | TEXT | yes | APPAREL, ELECTRONICS, HOME, BEAUTY, GROCERY, TOYS, SPORTS, BOOKS, JEWELRY, GIFT_CARD |  |  |  | = product.category |  |
| `qty` | INTEGER | yes |  | units |  |  | >= 1 |  |
| `unit_price` | DECIMAL | yes |  | USD |  |  |  |  |
| `line_discount` | DECIMAL | yes |  | USD |  |  |  | Line-level promotion / clearance markdown |
| `allocated_order_discount` | DECIMAL | yes |  | USD |  |  |  | Pro-rata share of order coupon |
| `net_amount` | DECIMAL | yes |  | USD |  |  | = qty*unit_price - line_discount - allocated_order_discount | Paid merchandise |
| `tax_amount` | DECIMAL | yes |  | USD |  |  | = round_half_up(net_amount * tax_rate); 0 if exempt |  |
| `line_total` | DECIMAL | yes |  | USD |  |  | = net_amount + tax_amount | Maximum refundable |
| `is_final_sale` | BOOLEAN | yes |  |  |  |  |  | Clearance item - not returnable unless merchant fault |

## `return_request` (ReturnRequest)

Customer return request (RMA header).

Primary key: `rma_id`

| Field | Type | Required | Allowed values / format | Unit | Unique | FK | Validation rule | Description |
|---|---|---|---|---|---|---|---|---|
| `rma_id` | TEXT | yes | `RMA-\d{4}-\d{6}` |  | yes |  |  |  |
| `order_id` | TEXT | yes |  |  |  | orders.order_id |  |  |
| `customer_id` | TEXT | yes |  |  |  | customer.customer_id | = orders.customer_id |  |
| `requested_at` | TIMESTAMP | yes |  |  |  |  | >= orders.delivered_at |  |
| `return_channel` | TEXT | yes | WEB, APP, STORE, CALL_CENTER |  |  |  |  |  |
| `resolution_type` | TEXT | yes | REFUND, EXCHANGE, STORE_CREDIT |  |  |  |  | What the customer asked for |
| `late_override_flag` | BOOLEAN | yes |  |  |  |  |  | Ops manager approved a late return |
| `override_by` | TEXT | no | `OPS-\d{3}` |  |  |  | required iff override |  |
| `override_reason` | TEXT | no | LOYAL_CUSTOMER, CARRIER_DELAY, SERVICE_RECOVERY |  |  |  | required iff override |  |
| `current_status` | TEXT | yes | SUBMITTED, AUTHORIZED, PARTIALLY_AUTHORIZED, REJECTED, IN_TRANSIT, EXPIRED, RECEIVED, LOST_IN_TRANSIT, INSPECTED, REFUNDED, EXCHANGED, CLOSED_NO_REFUND |  |  |  | = last status_event |  |

## `return_line` (ReturnLine)

Items and quantities the customer asks to return.

Primary key: `return_line_id`

| Field | Type | Required | Allowed values / format | Unit | Unique | FK | Validation rule | Description |
|---|---|---|---|---|---|---|---|---|
| `return_line_id` | TEXT | yes | `RMAL-RMA-\d{4}-\d{6}-\d{2}` |  | yes |  |  |  |
| `rma_id` | TEXT | yes |  |  |  | return_request.rma_id |  |  |
| `order_line_id` | TEXT | yes |  |  |  | order_line.order_line_id | order_line.order_id = rma.order_id |  |
| `sku` | TEXT | yes |  |  |  | product.sku | = order_line.sku |  |
| `requested_qty` | INTEGER | yes |  | units |  |  | >= 1 (may exceed purchased: exception path) |  |
| `return_reason` | TEXT | yes | CHANGED_MIND, WRONG_SIZE, NOT_AS_DESCRIBED, DEFECTIVE, DAMAGED_IN_TRANSIT, WRONG_ITEM |  |  |  |  |  |
| `item_opened` | BOOLEAN | yes |  |  |  |  |  | Customer-declared packaging opened |

## `return_authorization` (ReturnAuthorization)

Eligibility decision for an RMA (0..1 per RMA).

Primary key: `authorization_id`

| Field | Type | Required | Allowed values / format | Unit | Unique | FK | Validation rule | Description |
|---|---|---|---|---|---|---|---|---|
| `authorization_id` | TEXT | yes | `RA-\d{4}-\d{6}` |  | yes |  |  |  |
| `rma_id` | TEXT | yes |  |  | yes | return_request.rma_id |  |  |
| `decided_at` | TIMESTAMP | yes |  |  |  |  | >= requested_at |  |
| `decided_by_role` | TEXT | yes | SYSTEM_RULES, OPS_MANAGER |  |  |  |  |  |
| `decision_status` | TEXT | yes | AUTHORIZED, PARTIALLY_AUTHORIZED, REJECTED |  |  |  | derived from line decisions |  |
| `approved_qty_total` | INTEGER | yes |  | units |  |  | = sum(authorization_line.approved_qty) |  |
| `label_expires_at` | TIMESTAMP | no |  |  |  |  | decided_at + 14 days if any approved |  |

## `authorization_line` (AuthorizationLine)

Line-level decision (1:1 with return_line).

Primary key: `authorization_line_id`

| Field | Type | Required | Allowed values / format | Unit | Unique | FK | Validation rule | Description |
|---|---|---|---|---|---|---|---|---|
| `authorization_line_id` | TEXT | yes | `RAL-RMA-\d{4}-\d{6}-\d{2}` |  | yes |  |  |  |
| `authorization_id` | TEXT | yes |  |  |  | return_authorization.authorization_id |  |  |
| `return_line_id` | TEXT | yes |  |  | yes | return_line.return_line_id |  |  |
| `policy_id` | TEXT | yes |  |  |  | return_policy.policy_id |  | Policy version applied |
| `days_since_delivery` | INTEGER | yes |  | days |  |  |  |  |
| `effective_window_days` | INTEGER | yes |  | days |  |  |  | Policy window + loyalty extension |
| `prior_approved_qty` | INTEGER | yes |  | units |  |  |  | Approved on earlier RMAs for this order line |
| `approved_qty` | INTEGER | yes |  | units |  |  | <= requested_qty and <= qty - prior_approved_qty |  |
| `line_decision` | TEXT | yes | APPROVED, PARTIALLY_APPROVED, REJECTED |  |  |  |  |  |
| `decision_reason` | TEXT | yes | WITHIN_POLICY, QTY_CAPPED, REJECT_LATE, REJECT_EXCLUDED_CATEGORY, REJECT_FINAL_SALE, REJECT_HYGIENE_OPENED, REJECT_QTY_EXCEEDS_PURCHASED |  |  |  |  |  |
| `override_applied` | BOOLEAN | yes |  |  |  |  |  | Late, but approved via manager override |

## `return_shipment` (ReturnShipment)

Return label / parcel (1..N per authorized RMA).

Primary key: `shipment_id`

| Field | Type | Required | Allowed values / format | Unit | Unique | FK | Validation rule | Description |
|---|---|---|---|---|---|---|---|---|
| `shipment_id` | TEXT | yes | `RTS-\d{4}-\d{6}` |  | yes |  |  |  |
| `rma_id` | TEXT | yes |  |  |  | return_request.rma_id |  |  |
| `authorization_id` | TEXT | yes |  |  |  | return_authorization.authorization_id |  |  |
| `carrier` | TEXT | yes | UPS, FEDEX, USPS, DHL, STORE_DROPOFF |  |  |  |  |  |
| `tracking_number` | TEXT | yes |  |  | yes |  |  |  |
| `warehouse_id` | TEXT | yes | WH-01, WH-02, WH-03, WH-04 |  |  |  |  |  |
| `label_created_at` | TIMESTAMP | yes |  |  |  |  | >= authorization.decided_at |  |
| `shipped_at` | TIMESTAMP | no |  |  |  |  | >= label_created_at and <= label_expires_at |  |
| `received_at` | TIMESTAMP | no |  |  |  |  | >= shipped_at |  |
| `current_status` | TEXT | yes | LABEL_CREATED, IN_TRANSIT, RECEIVED, LOST, EXPIRED |  |  |  | = last status_event |  |

## `shipment_line` (ShipmentLine)

Bridge: return_shipment N:M return_line (split shipments).

Primary key: `shipment_id, return_line_id`

| Field | Type | Required | Allowed values / format | Unit | Unique | FK | Validation rule | Description |
|---|---|---|---|---|---|---|---|---|
| `shipment_id` | TEXT | yes |  |  |  | return_shipment.shipment_id |  |  |
| `return_line_id` | TEXT | yes |  |  |  | return_line.return_line_id |  |  |
| `shipped_qty` | INTEGER | yes |  | units |  |  | >= 1; sum per line <= approved_qty |  |

## `inspection` (Inspection)

Warehouse inspection of a received shipment line.

Primary key: `inspection_id`

| Field | Type | Required | Allowed values / format | Unit | Unique | FK | Validation rule | Description |
|---|---|---|---|---|---|---|---|---|
| `inspection_id` | TEXT | yes | `INS-\d{4}-\d{6}` |  | yes |  |  |  |
| `shipment_id` | TEXT | yes |  |  |  | return_shipment.shipment_id |  |  |
| `return_line_id` | TEXT | yes |  |  |  | return_line.return_line_id |  |  |
| `inspector_id` | TEXT | yes | `OPS-\d{3}` |  |  |  |  |  |
| `inspected_at` | TIMESTAMP | yes |  |  |  |  | >= shipment.received_at |  |
| `received_qty` | INTEGER | yes |  | units |  |  | 0..shipped_qty |  |
| `condition_grade` | TEXT | yes | UNOPENED, OPENED_LIKE_NEW, DAMAGED, DEFECTIVE, NOT_ORIGINAL_ITEM |  |  |  |  |  |
| `damage_attribution` | TEXT | yes | NONE, CUSTOMER, CARRIER, MANUFACTURER |  |  |  |  |  |
| `inspection_result` | TEXT | yes | PASS, FAIL |  |  |  | FAIL if customer damage, not original item, or short-shipped |  |

## `refund` (Refund)

Refund payout attempt (idempotent per RMA).

Primary key: `refund_id`

| Field | Type | Required | Allowed values / format | Unit | Unique | FK | Validation rule | Description |
|---|---|---|---|---|---|---|---|---|
| `refund_id` | TEXT | yes | `REF-\d{4}-\d{6}` |  | yes |  |  |  |
| `rma_id` | TEXT | yes |  |  |  | return_request.rma_id |  |  |
| `idempotency_key` | TEXT | yes |  |  |  |  |  | <rma_id>:REFUND:<n>; repeats are blocked |
| `attempt_seq` | INTEGER | yes |  |  |  |  | >= 1 |  |
| `refund_method` | TEXT | yes | ORIGINAL_PAYMENT, STORE_CREDIT |  |  |  |  |  |
| `requested_at` | TIMESTAMP | yes |  |  |  |  | >= last inspection |  |
| `processed_at` | TIMESTAMP | no |  |  |  |  | >= requested_at |  |
| `lines_amount` | DECIMAL | yes |  | USD |  |  | = sum(refund_line.line_refund_amount) |  |
| `shipping_refund` | DECIMAL | yes |  | USD |  |  |  | Original shipping, if merchant fault |
| `return_label_fee` | DECIMAL | yes |  | USD |  |  |  | Deducted for customer-reason mail returns |
| `refund_amount` | DECIMAL | yes |  | USD |  |  | = lines_amount + shipping_refund - return_label_fee |  |
| `paid_amount` | DECIMAL | yes |  | USD |  |  | = refund_amount if PAID else 0 |  |
| `current_status` | TEXT | yes | REQUESTED, PAID, BLOCKED_DUPLICATE |  |  |  | = last status_event |  |
| `blocked_reason` | TEXT | no |  |  |  |  |  |  |

## `refund_line` (RefundLine)

Refund calculation per inspected line.

Primary key: `refund_line_id`

| Field | Type | Required | Allowed values / format | Unit | Unique | FK | Validation rule | Description |
|---|---|---|---|---|---|---|---|---|
| `refund_line_id` | TEXT | yes | `REFL-REF-\d{4}-\d{6}-\d{2}` |  | yes |  |  |  |
| `refund_id` | TEXT | yes |  |  |  | refund.refund_id |  |  |
| `return_line_id` | TEXT | yes |  |  |  | return_line.return_line_id |  |  |
| `inspection_id` | TEXT | yes |  |  |  | inspection.inspection_id |  |  |
| `order_line_id` | TEXT | yes |  |  |  | order_line.order_line_id |  |  |
| `refund_qty` | INTEGER | yes |  | units |  |  | = inspection.received_qty |  |
| `merchandise_amount` | DECIMAL | yes |  | USD |  |  | = round_half_up(net_amount * refund_qty / qty) |  |
| `tax_amount` | DECIMAL | yes |  | USD |  |  | = round_half_up(line tax * refund_qty / qty) |  |
| `restocking_fee` | DECIMAL | yes |  | USD |  |  | merchandise * fee rate if opened & not merchant fault |  |
| `damage_deduction` | DECIMAL | yes |  | USD |  |  | 50% merchandise if customer damage |  |
| `cap_adjustment` | DECIMAL | yes |  | USD |  |  | reduces refund to remaining refundable |  |
| `line_refund_amount` | DECIMAL | yes |  | USD |  |  | = merchandise + tax - restocking_fee - damage_deduction - cap_adjustment |  |

## `inventory_disposition` (InventoryDisposition)

Decision on what happens to returned units.

Primary key: `disposition_id`

| Field | Type | Required | Allowed values / format | Unit | Unique | FK | Validation rule | Description |
|---|---|---|---|---|---|---|---|---|
| `disposition_id` | TEXT | yes | `DISP-\d{4}-\d{6}` |  | yes |  |  |  |
| `inspection_id` | TEXT | yes |  |  | yes | inspection.inspection_id |  |  |
| `return_line_id` | TEXT | yes |  |  |  | return_line.return_line_id |  |  |
| `sku` | TEXT | yes |  |  |  | product.sku |  |  |
| `qty` | INTEGER | yes |  | units |  |  | = inspection.received_qty |  |
| `disposition` | TEXT | yes | RESTOCK, REFURBISH, QUARANTINE, SCRAP |  |  |  |  |  |
| `decided_at` | TIMESTAMP | yes |  |  |  |  | >= inspection.inspected_at |  |
| `decided_by` | TEXT | yes | `OPS-\d{3}` |  |  |  |  |  |

## `inventory_movement` (InventoryMovement)

Stock movement produced by a disposition.

Primary key: `movement_id`

| Field | Type | Required | Allowed values / format | Unit | Unique | FK | Validation rule | Description |
|---|---|---|---|---|---|---|---|---|
| `movement_id` | TEXT | yes | `IMV-\d{4}-\d{6}` |  | yes |  |  |  |
| `disposition_id` | TEXT | yes |  |  | yes | inventory_disposition.disposition_id |  |  |
| `sku` | TEXT | yes |  |  |  | product.sku |  |  |
| `warehouse_id` | TEXT | yes | WH-01, WH-02, WH-03, WH-04 |  |  |  |  |  |
| `from_location` | TEXT | yes | RETURNS_DOCK, SELLABLE, REFURB_BENCH, QUARANTINE_CAGE, SCRAP_BIN |  |  |  |  |  |
| `to_location` | TEXT | yes | RETURNS_DOCK, SELLABLE, REFURB_BENCH, QUARANTINE_CAGE, SCRAP_BIN |  |  |  | determined by disposition |  |
| `qty` | INTEGER | yes |  | units |  |  |  |  |
| `unit_cost` | DECIMAL | yes |  | USD |  |  |  |  |
| `movement_value` | DECIMAL | yes |  | USD |  |  | = qty * unit_cost |  |
| `moved_at` | TIMESTAMP | yes |  |  |  |  | = disposition.decided_at |  |

## `status_event` (StatusEvent)

Append-only lifecycle history for orders, RMAs, shipments, refunds.

Primary key: `event_id`

| Field | Type | Required | Allowed values / format | Unit | Unique | FK | Validation rule | Description |
|---|---|---|---|---|---|---|---|---|
| `event_id` | TEXT | yes | `EVT-\d{4}-\d{7}` |  | yes |  |  |  |
| `entity_type` | TEXT | yes | ORDER, RETURN_REQUEST, RETURN_SHIPMENT, REFUND |  |  |  |  |  |
| `entity_id` | TEXT | yes |  |  |  |  |  | Polymorphic reference, validated per entity_type |
| `from_status` | TEXT | no |  |  |  |  |  | null for the creation event |
| `to_status` | TEXT | yes |  |  |  |  | allowed transition from from_status |  |
| `event_ts` | TIMESTAMP | yes |  |  |  |  | non-decreasing per entity |  |
| `actor_role` | TEXT | yes | CUSTOMER, SYSTEM, OPS_MANAGER, WAREHOUSE_OPERATOR, CARRIER, PAYMENT_GATEWAY |  |  |  |  |  |
| `actor_id` | TEXT | no |  |  |  |  |  |  |
| `reason_code` | TEXT | no |  |  |  |  |  |  |
