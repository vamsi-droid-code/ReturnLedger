# ReturnLedger

**A traceable, rule-driven returns (RMA) workflow with a reproducible synthetic dataset, an independent audit and measurable results.**

ReturnLedger models what happens after a customer clicks "Return item": the request is checked against the
return policy, authorized (fully, partially or not at all), shipped back, inspected in the warehouse, refunded
(or exchanged), and the units are restocked, refurbished, quarantined or scrapped. Every step is a separate record
that points to its parent, and every state change is appended to an event history, so any refund can be traced
back to the exact order line, policy version and inspection that justified it.

![Report screenshot](docs/images/report_top.png)

## What this project does

1. **Generates a realistic synthetic retail dataset** from one fixed seed (`20261022`): 12,000 customers,
   30,000 orders, 5,000 return requests and exactly 8,000 return lines, plus shipments, inspections, refunds,
   dispositions, inventory movements and about 140,000 lifecycle events.
2. **Applies documented business rules** (a policy engine in `returnledger/policy.py`) to decide eligibility,
   refund amounts and disposition. These outcomes are *calculated* from the source records, not randomly
   assigned.
3. **Injects five kinds of labelled process failures** (40 each at full scale) and writes them to a separate
   ground-truth file that never appears in the input tables:
   - return quantity exceeds purchased quantity
   - refund exceeds paid amount
   - restock before inspection
   - return after the policy window without an override
   - duplicate refund
4. **Validates the dataset**: 19 checks covering primary keys, foreign keys (including a database-enforced
   check in SQLite), enums, ID formats, date ordering, arithmetic reconciliation, quantity flow, lifecycle
   transitions and duplicates. A check fails only if it finds a violation that isn't a labelled anomaly.
5. **Audits the data independently**: `audit.py` reads only the exported CSVs, re-derives what the policy says
   should have happened and raises classified findings. These are scored against ground truth (precision and
   recall).
6. **Reports KPIs**: return rates by category, approval rate, refund economics, cycle times, disposition mix,
   inventory recovery, scenario coverage and leakage. Output is JSON plus a self-contained HTML report.
7. **Proves reproducibility**: the generator runs twice with the same seed and compares SHA-256 checksums of
   every exported file.

## Results (full dataset, seed 20261022)

| Measure | Result |
|---|---|
| Validation | **PASS**: 19/19 checks, 0 unlabelled violations |
| Anomaly detection vs ground truth | 200/200 found, 0 false positives (precision 100%, recall 100%) |
| Recorded decisions that match policy (clean lines) | 100% of 7,767 lines |
| Line approval rate | 83.75% (rejections: late 517, final sale 285, excluded category 205, quantity 181, hygiene 110) |
| Unit return rate | 12.5% overall; apparel 19.0%, gift cards 4.7% (never approved) |
| Refunds paid | $584,557.39 across 3,115 refunds (7.1% of order value) |
| Request to refund | median 14.2 days, 90th percentile 20.5 days |
| Inventory cost recovered | 65.6% (restock 5,325 units, refurbish 718, quarantine 656, scrap 1,235) |
| Duplicate payout attempts blocked by idempotency | 127 attempts ($21,379.75) |
| Leakage caused by the injected anomalies | $9,608.70 (all flagged by the audit) |
| Reproducibility | 39 files byte-identical across two runs (starter and full) |
| Robustness | 5 seeds at full scale and 20 at starter scale, each clean and with anomalies: 0 unlabelled violations |

Full details: [`data/full/reports/validation_summary.md`](data/full/reports/validation_summary.md),
[`evaluation.json`](data/full/reports/evaluation.json), [`metrics.json`](data/full/reports/metrics.json),
[`reproducibility.md`](data/full/reports/reproducibility.md), [`robustness.md`](data/full/reports/robustness.md),
and `report.html` (open it in a browser).

## Run it (VS Code)

Requirements: **Python 3.10+** only, using just the standard library (nothing to `pip install`).

1. `git clone https://github.com/vamsi-droid-code/ReturnLedger.git` and open the folder in VS Code
   (**File > Open Folder**).
2. Install the recommended **Python** extension when prompted.
3. Open **Run and Debug** (Ctrl+Shift+D), choose a configuration and press **F5**:
   - `1. Run pipeline - starter`: generates 3,000 orders, then validates, audits and reports (about 5 s)
   - `2. Run pipeline - full`: the full 30,000 order dataset (about 30 s)
   - `3. Reproducibility check`
   - `4. Explain one RMA end to end`: prompts for an RMA id and prints its whole trace
   - `5. Run tests`
4. Or use **Terminal > Run Task...** for the same commands, plus `open starter report` / `open full report`.
5. The Testing panel (beaker icon) also discovers the 28 unit tests.

### Command line equivalents

```bash
python -m returnledger run --scale starter          # generate + validate + audit + evaluate + report
python -m returnledger run --scale full             # 30k orders / 5k RMAs / 8k return lines
python -m returnledger run --scale 0.25 --seed 7    # any scale or seed, same generator
python -m returnledger reproduce --scale full       # generate twice, compare checksums
python -m returnledger robustness --scale full      # 5 seeds x (clean, with anomalies): 0 unlabelled violations
python -m returnledger explain --scale full --rma RMA-2026-000043
python -m returnledger docs                         # regenerate docs/DATA_DICTIONARY.md and docs/schema.sql
python -m unittest discover -s tests -v
```

`run` exits with code 1 if validation fails, so it can be used in CI.

### What a trace looks like

`explain` follows one RMA through every table. This one is an injected duplicate refund. It also shows a
short-shipped line: 2 units were approved, 1 was received, so only 1 was refunded.

```
RMA-2026-000043  status=REFUNDED  resolution=STORE_CREDIT  channel=APP
  lines:
    RMAL-RMA-2026-000043-01 BOOKS       bought=1 asked=1 reason=CHANGED_MIND paid=$24.37
      -> APPROVED qty=1 reason=WITHIN_POLICY days=6/30 policy=POL-BOOKS-V1
    RMAL-RMA-2026-000043-02 ELECTRONICS bought=2 asked=2 reason=WRONG_ITEM paid=$50.86
      -> APPROVED qty=2 reason=WITHIN_POLICY days=6/30 policy=POL-ELECTRONICS-V1
  inspection INS-2026-000069 RMAL-RMA-2026-000043-01 recv=1 UNOPENED/NONE PASS -> RESTOCK
  inspection INS-2026-000070 RMAL-RMA-2026-000043-02 recv=1 UNOPENED/NONE FAIL -> RESTOCK
  refund REF-2026-000039 PAID key=RMA-2026-000043:REFUND:1 ... = $49.80
  refund REF-2026-003225 PAID key=RMA-2026-000043:REFUND:2 ... = $49.80
  event history: ORDER PLACED -> ... -> RETURN_REQUEST REFUNDED -> second REFUND PAID
  audit findings:
    [HIGH] DUPLICATE_REFUND REF-2026-003225: second payout 49.80 after REF-2026-000039
```

## Workflow

```mermaid
flowchart LR
  C[Customer] -->|Order + OrderLines| O[(orders)]
  C -->|ReturnRequest + ReturnLines| R[RMA]
  R --> E{Eligibility rules<br/>window, exclusions,<br/>final sale, hygiene, qty}
  E -->|REJECTED| X[Closed]
  E -->|AUTHORIZED / PARTIAL| L[Return label<br/>ReturnShipment]
  L -->|not shipped in 14 days| EX[EXPIRED]
  L -->|carrier| T[IN_TRANSIT]
  T -->|lost| LO[LOST_IN_TRANSIT]
  T --> I[Inspection<br/>condition + attribution]
  I --> D{Disposition matrix}
  D --> RS[RESTOCK] & RF[REFURBISH] & Q[QUARANTINE] & S[SCRAP]
  I --> M{Resolution}
  M -->|exchange + PASS| EXO[Exchange order]
  M -->|refund / store credit| RE[Refund calc<br/>paid price - fees, capped]
  RE -->|idempotency key| P[PAID / BLOCKED_DUPLICATE]
```

## Key business rules (summary)

Full detail is in [docs/DESIGN.md](docs/DESIGN.md).

- **Return window** = category policy window (effective-dated by order date; apparel changed from 60 to 45 days on
  2026-07-01) + loyalty extension (GOLD +15, PLATINUM +30). A request on exactly the last day is on time; one day
  later it is late unless an ops manager recorded an override.
- **Exclusions**: gift cards are never returnable; groceries only for merchant-fault reasons; final-sale
  (clearance) lines and opened beauty items only for merchant-fault reasons. Overrides never bypass exclusions.
- **Quantity**: approved = min(requested, purchased minus quantity approved on earlier RMAs). This covers partial
  and repeat returns.
- **Refund** = returned share of the *paid* net amount (after line promotion and the pro-rata share of the order
  coupon) + the matching share of tax, minus a restocking fee (opened, non-fault electronics 15% / sports 10%),
  minus a 50% damage deduction for customer damage, and zero for a non-original item. The result is capped so the
  cumulative refund never exceeds what was paid. A $6.99 label fee applies to customer-reason mail returns, and
  original shipping is refunded once when the merchant is at fault.
- **Disposition** controls inventory movement: unopened goes to restock, opened electronics to refurbish, damaged
  goods to refurbish (if electronics or at least $100) or scrap, defective electronics/toys/home items to
  quarantine (vendor/safety), and non-original items to quarantine (fraud). Movement only happens after
  inspection.
- **Duplicate payouts**: one idempotency key per RMA; retries with the same key are recorded as
  `BLOCKED_DUPLICATE` with $0 paid.

## Repository layout

```
returnledger/            Python package (standard library only)
  config.py              seed, volumes, policy table, distributions
  schema.py              every table/field/enum/FK/lifecycle: single source of truth
  policy.py              business rules (pure functions)
  generator.py           seeded generator: master -> transactions -> events
  anomalies.py           labelled edge-case injection -> ground truth
  storage.py             CSV / JSON / SQL / SQLite export, loader, manifest
  validate.py            19 validation checks
  audit.py               independent exception detector
  evaluate.py            findings and decisions vs ground truth
  metrics.py, report.py  KPIs, HTML report, data dictionary
  __main__.py            CLI
tests/                   unit tests (rules) + end-to-end pipeline tests
data/starter/            3k-order dataset: csv/, json/, sql/, ground_truth/, reports/, manifest.json
data/full/               30k-order dataset: csv/, ground_truth/, reports/, manifest.json
docs/                    DATA_DICTIONARY.md, DESIGN.md, schema.sql, AI_USAGE.md
prompts/PROMPT_HISTORY.md  every prompt given to the AI tool
```

`data/full/json`, `data/full/sql` and the `.db` files (about 165 MB) aren't committed. Running
`python -m returnledger run --scale full` regenerates them byte-for-byte. The checksums for every file are in
`data/full/manifest.json`.

## Data provenance and lawful use

No external data is used. Every record comes from the seeded generator. Customer names are random
combinations of common first and last names, emails use the reserved `example.com` domain, and tax rates are
illustrative. See `provenance` in each `manifest.json`. Code and data are released under the MIT License.

## Limitations and next steps

- The audit uses the same policy functions as the generator, so 100% precision and recall shows that the data
  and the rules are consistent. It isn't a benchmark of a learned model. A natural next step is to train or
  test a detector that cannot see the rules, using ground truth as labels.
- The model is simplified in places: one warehouse per RMA, exchanges are like-for-like at $0, no partial
  refunds for lost parcels (lost parcels stay unrefunded pending a carrier claim), and no multi-currency or
  multi-jurisdiction tax rules.
- Ground truth labels each anomaly at its primary entity. Secondary effects (for example, phantom inventory
  from an over-approved quantity) are documented but not labelled separately.
- Next steps: a REST API or small UI over the SQLite database, policy versions managed as data instead of
  config, and fraud signals such as serial returners or empty-box rates.

## AI usage

This project was built with an AI coding assistant (Claude in Cursor). See
[docs/AI_USAGE.md](docs/AI_USAGE.md) for what was AI-generated and what was reviewed and verified, and
[prompts/PROMPT_HISTORY.md](prompts/PROMPT_HISTORY.md) for every prompt.
