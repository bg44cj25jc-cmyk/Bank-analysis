# Project status

StatementBridge converts Indian bank statement PDFs into Tally-ready output for
one financial year, offline. Built for SuhagKuti Tax & Legal Services.

**Last updated:** step 4 (rules engine), all four gates closed.

## Where the project actually stands

| Phase | Scope | State |
|---|---|---|
| 1 | Parser core: money, frame, traps, balance chain and repair | **built, does not meet its accuracy bar** |
| 2 | OCR pipeline, bank profiles, audit and CLI | built |
| 3 | Capture-quality gate, per-page routing, FastAPI service, job queue, worker | built |
| **4** | **Rules engine: categories, Tally ledgers, contra, category summary** | **built** |
| 5 | Excel export | not started |
| 6 | GUI | not started |
| 7 | Sessions, roles, user-created rules | not started |
| 8 | Tally XML export, Ollama | not started |

Phases 5–8 are named in forward references left in the code: `api/deps.py`,
`store/models.py` and `store/audit.py` all say what step 7 replaces.

## The thing to know first

**Phase 1 does not meet its acceptance bar, and phase 4 does not change that.**

The bar is a paisa-exact reconciliation with under 5% of rows unresolved. Both
sample statements are 150 DPI scans — half what Tesseract expects — and the
Gramin ledger is 1-bit dot-matrix on top of that. Measured row agreement is about
**38% on Gramin and far lower on SBI**. The repair engine fixes isolated errors
correctly, but its premise is that errors are sparse; at this density conflicts
are adjacent more often than isolated and which field is wrong becomes genuinely
undecidable. It refuses to guess, so rows land in `UNRESOLVED` rather than
quietly wrong.

Rendering higher does not help — interpolation cannot add detail the capture
never recorded (300 DPI: 45%, 450: 21%, 600: 11%).

**A 300–400 DPI optical rescan is the single change that would move this most.**
`statementbridge quality` now catches this at upload in about a third of a
second, and `docs/SCANNING_SOP.md` is the office-facing one-pager that prevents
it.

Nothing downstream of extraction can be better than its input. A category is
right or wrong independently of whether the amount beside it survived the scan —
but an export still needs both.

## What step 4 delivered

A deterministic, auditable classifier: every settled row gets a category, a Tally
ledger, a contra flag and the id of the rule that decided it. See
[docs/RULES.md](RULES.md).

Measured against the 236 rows of the client's own migration workbook that a
person categorised by hand: **236/236 on category, ledger and contra alike**,
with one documented divergence on 5 rows. That corpus exercises 10 of 35
categories and 11 of 76 rules, which is the real limit on what the number means.

### What each gate closed

| Gate | Delivered | What it changed |
|---|---|---|
| 1 | Taxonomy, narration normaliser, rule format | Established that a rule is data and that a rule contradicting its category is rejected at build time |
| 2 | Engine, default pack (76 rules), category summary | Three orderings turned out to be load-bearing; the summary must tie to the balance chain |
| 3 | Regression against the 236 labelled rows | Caught the engine posting to `MR. AJOY NAG - Own Accounts` where the firm keeps `Ajoy Nag - Own Accounts` — the category was right on all 41 rows and only the Tally posting was wrong |
| 4 | Wiring: frame, worker, API, CLI, SQLite migration | Classification now happens on the worker, where the rows are, and travels back with the result |

### Two deliberate departures from the client's workbook

Both were raised and confirmed rather than assumed:

1. **`RTGS_IN` / `RTGS_OUT` are new codes.** Their sheet has 33 rows and ours has
   35. The alternative was labelling a wire transfer as NEFT.
2. **PhonePe's IMPS settlements get the aggregator ledger**, as its NEFT ones
   already did. The sheet's inconsistency is an artefact of the rails: NEFT
   prints `PHONEPE LIMITED` with a space, IMPS runs it together, so the person
   working by hand recognised the payer on one rail and not the other.

`ATM_WITHDRAWAL` is also flagged contra where the workbook flags only `F` and
`S` — but that category has a count of zero in their statement, so it was never
exercised rather than deliberately excluded.

## What phase 5 needs from here

Excel export has everything it requires: a settled frame with classification
columns, a category summary that ties, and a ledger list. The blocker is not
structural — it is that the fixtures do not reconcile, so there is nothing yet
worth exporting from them.

## Running it

```
pip install -e ".[dev]"          # parser core and tests
pip install -e ".[api]"          # the service layer
pytest -m "not slow"             # unit tests, no fixtures needed
pytest                           # everything, including full-document OCR
```

Requires Poppler (`pdftoppm`, `pdfinfo`) and Tesseract 5 on PATH.

Fixtures live in the `Ba-resources` repository and are found from a sibling
checkout or via `SB_FIXTURE_DIR`. Tests skip cleanly when they are absent.

## Tests

259 tests pass. The regression suites divide on a principle worth keeping:

- **`tests/regression/test_fixtures.py` pins floors**, because extraction
  accuracy is measured through Tesseract and row agreement moves between
  recogniser versions (37.8% against 45.5% on the same fixture). Those
  thresholds are set under the measured values as a floor to defend, **not a
  target that has been hit**. Raise them when rescans arrive.
- **`tests/regression/test_ledger_corpus.py` asserts exact values**, because
  nothing in it touches a recogniser. The same input gives the same answer on
  every machine, so a floor would only hide a silent reclassification.
