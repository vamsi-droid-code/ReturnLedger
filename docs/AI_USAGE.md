# AI usage disclosure

## Tools used
- **Cursor** (desktop IDE) with its AI agent, backed by an Anthropic Claude model. The agent could read and
  write files, run terminal commands and open a browser tab to view the generated report.
- No other AI tools were used. The full list of prompts is in [../prompts/PROMPT_HISTORY.md](../prompts/PROMPT_HISTORY.md).
- The agent made the git commits. Cursor automatically adds a `Co-authored-by: Cursor` line to such commits;
  I removed it from the commit messages (no files changed) because this document is where AI use is disclosed.

## Where AI accelerated the work
- **Translating the brief into a design**: entity list, the extra entities that were needed (authorization
  lines, a shipment bridge table, effective-dated policies, inventory movements, an event log), the ID scheme
  and lifecycle state machines.
- **Writing almost all of the code**: the schema-as-source-of-truth approach, policy engine, generator,
  anomaly injector, exporters, validation suite, audit, metrics, HTML report and CLI.
- **Documentation**: README, design notes and the generated data dictionary.
- **The web UI** (`returnledger/webapp.py`, `returnledger/web/`): a read-only explorer added after the core
  pipeline, so the data can be understood without reading CSVs. It only reads the exported files and reports.

## Where I relied heavily on it
- The specific business-rule values (window lengths, fee rates, the disposition matrix and distribution
  shares) were proposed by the AI as *plausible* retail defaults. They aren't from a real retailer's policy.
  They are centralised in `returnledger/config.py` so they can be reviewed and changed in one place.
- The structure of the validation checks and the evaluation metrics.

## What was reviewed, changed or validated
- **Verified by running, not by reading**: the full pipeline was run at starter and full scale, and every
  number quoted in the README comes from generated report files (`data/*/reports/`).
- **Unit tests pin the rules**, including boundary cases (last day of the window, loyalty extension, effective
  dates, exclusion precedence over override, rounding and refund caps).
- **Bugs found during verification and fixed** (visible in the git history):
  1. Some events (a closed-no-refund status, label creation, blocked retries) could fall *after* the as-of
     cut-off. This was caught by a full-scale run with injection disabled, which must show zero violations. That
     check is now also a unit test.
  2. An anomaly cascade: an injected over-refund on one RMA pushed a legitimate refund on a *sibling* RMA of
     the same order over the order total, which produced an unlabelled violation. This was caught by the
     multi-seed robustness run (seeds 2 and 3) and fixed by excluding orders with several RMAs from
     injection.
  3. Windows line-ending conversion would have invalidated the published checksums after checkout, so
     `.gitattributes` now forces LF.
- **Manual spot checks** with `python -m returnledger explain --rma ...` on anomalous and boundary RMAs. The
  refund arithmetic in the README example was checked by hand: $22.99 + $1.38 = $24.37 and
  $23.99 + $1.44 = $25.43, for a total of $49.80.
- **Report checked visually** in a browser (screenshot in `docs/images/report_top.png`).
- **Submission checks**: before publishing, the tracked files were scanned for secrets, credentials, local paths
  and personal data (none found), and every number in [VERIFICATION.md](VERIFICATION.md) was re-measured from a
  fresh run rather than copied from earlier notes. The run time in the README was corrected (about 60 s, not 30 s).
- **Web UI checked page by page** in a browser. This caught wording bugs in the generated RMA summaries
  ("asked to store credit", "1 days") and IDs wrapping badly in narrow windows. All were fixed before commit.

## Honest limitations of the AI-assisted approach
- The audit and the generator share the same rule functions, so the 100% detection score demonstrates
  internal consistency, not independent detection skill (see README, "Limitations").
- Synthetic distributions are plausible but not calibrated to real data.
- The whole build happened in one assistant session, so the commits were made in quick succession. They are
  still split by concern (schema, rules, generator, anomalies, storage, validation, reporting, fixes, data,
  docs) so the evolution is readable.
