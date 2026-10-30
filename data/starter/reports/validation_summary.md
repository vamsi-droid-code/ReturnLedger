# Validation summary

Dataset: seed `20261022`, scale `0.1`, as-of `2026-10-25T23:59:59`

**Overall: PASS**: 19/19 checks passed, 0 unlabelled violations, 55 violations explained by labelled ground-truth anomalies.

| Category | Check | Rows checked | Violations | Labelled | Unlabelled | Status |
|---|---|---:|---:|---:|---:|---|
| structure | Primary keys unique | 32,236 | 0 | 0 | 0 | PASS |
| structure | Required fields present | 32,236 | 0 | 0 | 0 | PASS |
| structure | Enum values allowed | 32,236 | 0 | 0 | 0 | PASS |
| structure | ID / format patterns | 32,236 | 0 | 0 | 0 | PASS |
| structure | Unique columns | 32,236 | 0 | 0 | 0 | PASS |
| integrity | Foreign keys resolve (incl. composite + polymorphic) | 48,058 | 0 | 0 | 0 | PASS |
| integrity | SQLite PRAGMA foreign_key_check | 13,973 | 0 | 0 | 0 | PASS |
| integrity | Cross-entity joins consistent | 14,613 | 0 | 0 | 0 | PASS |
| volume | Target volumes met exactly | 3 | 0 | 0 | 0 | PASS |
| dates | Date ordering across the lifecycle | 26,650 | 10 | 10 | 0 | PASS_WITH_LABELLED_EXCEPTIONS |
| arithmetic | Totals, tax, discounts and refund formulas reconcile | 11,065 | 0 | 0 | 0 | PASS |
| arithmetic | Refunds <= amount paid (line and order) | 302 | 10 | 10 | 0 | PASS_WITH_LABELLED_EXCEPTIONS |
| quantity | Quantities flow purchased >= approved >= shipped >= received = disposed | 2,720 | 5 | 5 | 0 | PASS_WITH_LABELLED_EXCEPTIONS |
| lifecycle | Lifecycle transitions legal and statuses derived from history | 18,859 | 0 | 0 | 0 | PASS |
| duplicates | Duplicate payouts blocked; no duplicate lines or events | 324 | 5 | 5 | 0 | PASS_WITH_LABELLED_EXCEPTIONS |
| business_rules | Eligibility decisions follow policy | 798 | 10 | 10 | 0 | PASS_WITH_LABELLED_EXCEPTIONS |
| business_rules | Refund math follows paid price, discounts, tax and fees | 313 | 5 | 5 | 0 | PASS_WITH_LABELLED_EXCEPTIONS |
| business_rules | Duplicate payouts detected | 313 | 5 | 5 | 0 | PASS_WITH_LABELLED_EXCEPTIONS |
| business_rules | Disposition follows inspection and matrix | 625 | 5 | 5 | 0 | PASS_WITH_LABELLED_EXCEPTIONS |

`PASS_WITH_LABELLED_EXCEPTIONS` means every violation found is a deliberately injected anomaly recorded in `ground_truth/ground_truth_anomalies.csv`.
