# Reproducibility check

Generated the `starter` dataset twice with seed `20261022` into separate folders and compared every exported file. **Result: IDENTICAL** (39 files).

| File | Rows (run A) | Rows (run B) | SHA-256 (first 16) | Identical |
|---|---:|---:|---|---|
| csv/authorization_line.csv | 798 | 798 | `e17001f26f0283d5` | yes |
| csv/customer.csv | 1,200 | 1,200 | `0784d14f5686d0c3` | yes |
| csv/inspection.csv | 626 | 626 | `f94bfb0bc50a32c9` | yes |
| csv/inventory_disposition.csv | 625 | 625 | `52aa3d3c0f5dd2fd` | yes |
| csv/inventory_movement.csv | 625 | 625 | `b0bf61809ef56d80` | yes |
| csv/order_line.csv | 6,050 | 6,050 | `fd1acacac111eef2` | yes |
| csv/orders.csv | 3,106 | 3,106 | `636589f9bb8cedaf` | yes |
| csv/product.csv | 1,500 | 1,500 | `aed7d5af6ea951aa` | yes |
| csv/refund.csv | 313 | 313 | `c485279979fb302f` | yes |
| csv/refund_line.csv | 472 | 472 | `9bfe52b7a98b5701` | yes |
| csv/return_authorization.csv | 499 | 499 | `04d3a4c05f75722c` | yes |
| csv/return_line.csv | 800 | 800 | `eb555bd8f5b46128` | yes |
| csv/return_policy.csv | 11 | 11 | `53978a1dea9bba31` | yes |
| csv/return_request.csv | 500 | 500 | `01e8e5fd7a8ac9dc` | yes |
| csv/return_shipment.csv | 467 | 467 | `424b9e9802b04371` | yes |
| csv/shipment_line.csv | 671 | 671 | `53efb8ca124f132b` | yes |
| csv/status_event.csv | 13,973 | 13,973 | `9a4a3e364c1a3da5` | yes |
| ground_truth/ground_truth_anomalies.csv | 25 | 25 | `a29d84402d2f2e2e` | yes |
| ground_truth/ground_truth_anomalies.json | 25 | 25 | `356609c7d4529539` | yes |
| ground_truth/ground_truth_labels.csv | 800 | 800 | `96b65cf156c0318f` | yes |
| json/authorization_line.json | 798 | 798 | `8ecb5a25048c701a` | yes |
| json/customer.json | 1,200 | 1,200 | `c3942e6be57334e3` | yes |
| json/inspection.json | 626 | 626 | `1dbf5044e9c2ac16` | yes |
| json/inventory_disposition.json | 625 | 625 | `b3d23f3ab8e3b113` | yes |
| json/inventory_movement.json | 625 | 625 | `3c0f1bc73f945c34` | yes |
| json/order_line.json | 6,050 | 6,050 | `bdcd6b8e76426dce` | yes |
| json/orders.json | 3,106 | 3,106 | `ec92882e7f59df9d` | yes |
| json/product.json | 1,500 | 1,500 | `de50560b43f90cd3` | yes |
| json/refund.json | 313 | 313 | `6b27665dfc5fdecb` | yes |
| json/refund_line.json | 472 | 472 | `5e64232cbb808fb9` | yes |
| json/return_authorization.json | 499 | 499 | `e71a3634c96731f2` | yes |
| json/return_line.json | 800 | 800 | `804611a2e0ff0292` | yes |
| json/return_policy.json | 11 | 11 | `1f96971cd2c50bb2` | yes |
| json/return_request.json | 500 | 500 | `0d607ab7b36919bf` | yes |
| json/return_shipment.json | 467 | 467 | `5598fb3e5d51a04a` | yes |
| json/shipment_line.json | 671 | 671 | `c3734145c390eae3` | yes |
| json/status_event.json | 13,973 | 13,973 | `57033ae13bc9ae65` | yes |
| sql/schema.sql | 17 | 17 | `0acd4fbd1eab1764` | yes |
| sql/seed.sql | 32,236 | 32,236 | `0a044263a0eb4374` | yes |
