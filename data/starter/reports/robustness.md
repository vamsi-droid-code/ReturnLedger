# Robustness check

Each seed is generated twice at scale 0.1: clean (no injection) and with labelled anomalies. A run passes when validation has zero unlabelled violations and the audit has zero false positives/negatives.
**Result: ALL PASSED**

| Seed | Anomalies injected | Validation | Violations | Unlabelled | Ground truth | TP | FP | FN | Pass |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| 20261022 | False | PASS | 0 | 0 | 0 | 0 | 0 | 0 | yes |
| 20261022 | True | PASS | 55 | 0 | 25 | 25 | 0 | 0 | yes |
| 1 | False | PASS | 0 | 0 | 0 | 0 | 0 | 0 | yes |
| 1 | True | PASS | 55 | 0 | 25 | 25 | 0 | 0 | yes |
| 2 | False | PASS | 0 | 0 | 0 | 0 | 0 | 0 | yes |
| 2 | True | PASS | 54 | 0 | 25 | 25 | 0 | 0 | yes |
| 3 | False | PASS | 0 | 0 | 0 | 0 | 0 | 0 | yes |
| 3 | True | PASS | 55 | 0 | 25 | 25 | 0 | 0 | yes |
| 42 | False | PASS | 0 | 0 | 0 | 0 | 0 | 0 | yes |
| 42 | True | PASS | 55 | 0 | 25 | 25 | 0 | 0 | yes |
