# Validation summary

Dataset: seed `20261022`, scale `1.0`, as-of `2026-10-25T23:59:59`

**Overall: PASS**: 19/19 checks passed, 0 unlabelled violations, 438 violations explained by labelled ground-truth anomalies.

| Category | Check | Rows checked | Violations | Labelled | Unlabelled | Status |
|---|---|---:|---:|---:|---:|---|
| structure | Primary keys unique | 309,159 | 0 | 0 | 0 | PASS |
| structure | Required fields present | 309,159 | 0 | 0 | 0 | PASS |
| structure | Enum values allowed | 309,159 | 0 | 0 | 0 | PASS |
| structure | ID / format patterns | 309,159 | 0 | 0 | 0 | PASS |
| structure | Unique columns | 309,159 | 0 | 0 | 0 | PASS |
| integrity | Foreign keys resolve (incl. composite + polymorphic) | 481,361 | 0 | 0 | 0 | PASS |
| integrity | SQLite PRAGMA foreign_key_check | 139,843 | 0 | 0 | 0 | PASS |
| integrity | Cross-entity joins consistent | 146,339 | 0 | 0 | 0 | PASS |
| volume | Target volumes met exactly | 3 | 0 | 0 | 0 | PASS |
| dates | Date ordering across the lifecycle | 266,302 | 80 | 80 | 0 | PASS_WITH_LABELLED_EXCEPTIONS |
| arithmetic | Totals, tax, discounts and refund formulas reconcile | 111,067 | 0 | 0 | 0 | PASS |
| arithmetic | Refunds <= amount paid (line and order) | 3,115 | 78 | 78 | 0 | PASS_WITH_LABELLED_EXCEPTIONS |
| quantity | Quantities flow purchased >= approved >= shipped >= received = disposed | 27,062 | 40 | 40 | 0 | PASS_WITH_LABELLED_EXCEPTIONS |
| lifecycle | Lifecycle transitions legal and statuses derived from history | 188,750 | 0 | 0 | 0 | PASS |
| duplicates | Duplicate payouts blocked; no duplicate lines or events | 3,391 | 40 | 40 | 0 | PASS_WITH_LABELLED_EXCEPTIONS |
| business_rules | Eligibility decisions follow policy | 7,987 | 80 | 80 | 0 | PASS_WITH_LABELLED_EXCEPTIONS |
| business_rules | Refund math follows paid price, discounts, tax and fees | 3,264 | 40 | 40 | 0 | PASS_WITH_LABELLED_EXCEPTIONS |
| business_rules | Duplicate payouts detected | 3,264 | 40 | 40 | 0 | PASS_WITH_LABELLED_EXCEPTIONS |
| business_rules | Disposition follows inspection and matrix | 6,185 | 40 | 40 | 0 | PASS_WITH_LABELLED_EXCEPTIONS |

`PASS_WITH_LABELLED_EXCEPTIONS` means every violation found is a deliberately injected anomaly recorded in `ground_truth/ground_truth_anomalies.csv`.
