# How the core functionality was verified

Every claim in the README can be re-checked on your machine with the commands below. Nothing here relies on
reading the code: each step runs the code and compares its output to something independent (a hand-computed
value, a separate answer key, a second run, or the committed files).

Last full re-run: 2026-10-31, Windows 11, Python 3.13, from a clean working tree. The full-scale run took about
60 s and peaked at about 500 MB of memory.

## 1. Unit and end-to-end tests

```bash
python -m unittest discover -s tests -v
```

Result: `Ran 32 tests ... OK` (about 3 s).

| Test file | What it pins down |
| --- | --- |
| `tests/test_policy.py` (20) | Business rules on hand-made inputs: last day of the window is on time and the next day is late, loyalty extension, effective-dated apparel policy (60 days before 2026-07-01, 45 after), exclusions beat overrides, quantity cap across repeat returns, half-up cent rounding, refund formula and cap, restocking fee, damage deduction, label fee, disposition matrix |
| `tests/test_pipeline.py` (8) | Generates a small dataset and checks exact volumes, ID formats, that all 19 validation checks pass (keys, foreign keys, arithmetic and so on), that every anomaly type is present, that ground truth never leaks into input tables, that a clean run (no injected anomalies) has zero violations, that the audit finds every planted anomaly, and that the same seed gives identical data while a new seed gives different data |
| `tests/test_webapp.py` (4) | Starts the web server on a free port and checks every API endpoint, the full RMA list, an RMA trace with its ground truth, and that unknown IDs and path-traversal attempts return 404 |

## 2. The pipeline end to end (validation, audit, scoring)

```bash
python -m returnledger run --scale starter   # about 2-5 s
python -m returnledger run --scale full      # about 30-60 s
```

Each run generates the data, validates it, audits it, scores the audit against ground truth and writes reports.
The command exits with code 1 if validation fails. Output from the full run:

```
validation          : PASS (19/19 checks, 0 unlabelled violations)
anomaly detection   : precision 100.00%, recall 100.00%
clean decisions     : 100.00% match policy
approval rate       : 83.75% of lines
refunds paid        : $584,557.39
```

How to read this:

- **Validation** runs 19 checks (keys, foreign keys, enums, ID formats, date order, arithmetic, quantity flow,
  lifecycle transitions, duplicates, business rules). A check *fails* only if it finds a violation that is not
  in the ground-truth file. So "PASS with labelled exceptions" means it found exactly the planted mistakes and
  nothing else. Detail: [`data/full/reports/validation_summary.md`](../data/full/reports/validation_summary.md).
- **Anomaly detection** compares `audit_findings.csv` (produced from the exported CSVs only) with
  `ground_truth/ground_truth_anomalies.csv`. 200 planted, 200 found, 0 false alarms.
  Detail: [`data/full/reports/evaluation.json`](../data/full/reports/evaluation.json).
- **Clean decisions** recomputes the policy decision for every line that was not tampered with and compares it to
  the recorded decision.

## 3. Reproducibility

```bash
python -m returnledger reproduce --scale starter
python -m returnledger reproduce --scale full
```

Generates the dataset twice into separate folders and compares the SHA-256 of every exported file.
Result: `39 files compared across two runs: IDENTICAL` at both scales.
Detail: [`data/full/reports/reproducibility.md`](../data/full/reports/reproducibility.md).

A stronger check: after `run --scale starter` and `run --scale full`, `git status` shows **no changes**. A fresh
run reproduces every committed CSV, ground-truth file, manifest and report byte for byte. The checksums are also
listed in each `manifest.json`. A fresh `git clone` from GitHub was checked the same way.

## 4. Robustness across seeds

```bash
python -m returnledger robustness --scale full
```

Runs seeds 20261022, 1, 2, 3 and 42, each with and without injected anomalies. Requirement: zero unlabelled
violations in every case, and zero violations of any kind in the clean runs. All pass (20 seeds were also run at
starter scale). This step found two real bugs during development (see [AI_USAGE.md](AI_USAGE.md)).
Detail: [`data/full/reports/robustness.md`](../data/full/reports/robustness.md).

## 5. Manual spot checks

- `python -m returnledger explain --scale full --rma RMA-2026-000043` prints one return through every table.
  Its refund was checked by hand: $22.99 + $1.38 tax = $24.37 and $23.99 + $1.44 = $25.43, for $49.80 in total.
  The second, duplicate $49.80 payout is flagged by the audit and is in the answer key.
- One example of each planted mistake was opened in the web UI (Overview page, "Examples") and read against the
  rule it breaks.
- The HTML report and every web UI page were checked visually in a browser (screenshots in `docs/images/`).

## What this verification does not prove

- The audit reuses the same policy functions as the generator, so 100% precision and recall shows the data and
  the rules agree with each other. It is not evidence that the rules match a real retailer, or that a detector
  without access to the rules would do as well.
- Business-rule values (window lengths, fees, distributions) are plausible defaults, not calibrated to real
  data. They are all in `returnledger/config.py`.
- Testing was done on Windows with Python 3.13. The code uses only the standard library and forces LF line
  endings, so Linux and macOS are expected to give identical checksums, but they were not tested directly.
