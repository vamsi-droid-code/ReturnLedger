# Reproducibility check

Generated the `full` dataset twice with seed `20261022` into separate folders and compared every exported file. **Result: IDENTICAL** (39 files).

| File | Rows (run A) | Rows (run B) | SHA-256 (first 16) | Identical |
|---|---:|---:|---|---|
| csv/authorization_line.csv | 7,987 | 7,987 | `4a82ab40b4cb5ad7` | yes |
| csv/customer.csv | 12,000 | 12,000 | `11e575a19388661c` | yes |
| csv/inspection.csv | 6,202 | 6,202 | `7d03ca711bcb87d4` | yes |
| csv/inventory_disposition.csv | 6,185 | 6,185 | `4341cf556018ed67` | yes |
| csv/inventory_movement.csv | 6,185 | 6,185 | `8b66993bc85eb6ca` | yes |
| csv/order_line.csv | 60,764 | 60,764 | `9088974fa3df6bd0` | yes |
| csv/orders.csv | 30,967 | 30,967 | `201cb71d6f64810e` | yes |
| csv/product.csv | 1,500 | 1,500 | `aed7d5af6ea951aa` | yes |
| csv/refund.csv | 3,264 | 3,264 | `b665125f0fe26421` | yes |
| csv/refund_line.csv | 4,895 | 4,895 | `19ce56b122ecdaae` | yes |
| csv/return_authorization.csv | 4,992 | 4,992 | `82588243c4e9100e` | yes |
| csv/return_line.csv | 8,000 | 8,000 | `d929264301947cfa` | yes |
| csv/return_policy.csv | 11 | 11 | `53978a1dea9bba31` | yes |
| csv/return_request.csv | 5,000 | 5,000 | `12818c614f377c6d` | yes |
| csv/return_shipment.csv | 4,676 | 4,676 | `52f82f8769360bab` | yes |
| csv/shipment_line.csv | 6,688 | 6,688 | `50c6c1d78bb80db3` | yes |
| csv/status_event.csv | 139,843 | 139,843 | `cb71c21af44e0d1c` | yes |
| ground_truth/ground_truth_anomalies.csv | 200 | 200 | `7191706ec9af3a2b` | yes |
| ground_truth/ground_truth_anomalies.json | 200 | 200 | `8c2cd711023437e7` | yes |
| ground_truth/ground_truth_labels.csv | 8,000 | 8,000 | `e3b17fe1a7828106` | yes |
| json/authorization_line.json | 7,987 | 7,987 | `cc47a5a4808f9ba2` | yes |
| json/customer.json | 12,000 | 12,000 | `594580cc9d4ae3c5` | yes |
| json/inspection.json | 6,202 | 6,202 | `1e9e19a216eaa0c6` | yes |
| json/inventory_disposition.json | 6,185 | 6,185 | `be0943833e55d8b6` | yes |
| json/inventory_movement.json | 6,185 | 6,185 | `42e6df18d81bcf4c` | yes |
| json/order_line.json | 60,764 | 60,764 | `44db27d5736510ce` | yes |
| json/orders.json | 30,967 | 30,967 | `bb6ab694401f5ca6` | yes |
| json/product.json | 1,500 | 1,500 | `de50560b43f90cd3` | yes |
| json/refund.json | 3,264 | 3,264 | `7b937d315de2a39b` | yes |
| json/refund_line.json | 4,895 | 4,895 | `169cb20465e6d4e7` | yes |
| json/return_authorization.json | 4,992 | 4,992 | `a0673b00cc5699eb` | yes |
| json/return_line.json | 8,000 | 8,000 | `6bc950ed68e6d13e` | yes |
| json/return_policy.json | 11 | 11 | `1f96971cd2c50bb2` | yes |
| json/return_request.json | 5,000 | 5,000 | `cd29d55c557b4f48` | yes |
| json/return_shipment.json | 4,676 | 4,676 | `56555b5d5d8a7c31` | yes |
| json/shipment_line.json | 6,688 | 6,688 | `35423c0d8cf8bdc1` | yes |
| json/status_event.json | 139,843 | 139,843 | `28089920937b5765` | yes |
| sql/schema.sql | 17 | 17 | `0acd4fbd1eab1764` | yes |
| sql/seed.sql | 309,159 | 309,159 | `7bf2a5ac2d2c2d81` | yes |
