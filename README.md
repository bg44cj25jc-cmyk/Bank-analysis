# StatementBridge

Converts Indian bank statement PDFs into Tally-ready output for one financial
year. Offline by default: nothing leaves the machine.

Built for SuhagKuti Tax & Legal Services. **Phase 1 (parser core) — CLI only.**

## Status

Phase 1 is built and does not yet meet its acceptance bar. The extraction path
runs end to end on both sample statements, and the balance engine is complete
and tested, but the fixtures do not reconcile. The cause is measured and is not
a software defect — see [Why the fixtures do not reconcile](#why-the-fixtures-do-not-reconcile).

| Component | State |
|---|---|
| Decimal / Indian money handling | done |
| Trap and row classifier | done |
| Balance chain and repair engine | done |
| OCR pipeline (dot-matrix and ruled-table) | done |
| Digital-text parser (pdfplumber) | done, synthetic tests only |
| Bank profiles, audit and CLI | done |
| **PySide6 GUI** (Queue, Review, Reconcile, audit trail) | **done** (Phase 4, taken early) |
| Export / Accuracy screens | shells — the writers are Phases 3 and 5 |
| Rules engine, Excel, Tally XML, Ollama | not started |

The GUI was brought forward ahead of the rules engine deliberately. Its Review
and Reconcile screens are what make a statement that does not reconcile
*workable* — they turn the balance engine's diagnoses into a work queue rather
than a log file — and at the current OCR accuracy that matters more than
automatic categorisation.

```
pip install PySide6
python -m statementbridge.gui.app                       # run it
QT_QPA_PLATFORM=offscreen python tools/shoot.py out/    # render every screen to PNG
```

## Install

```
pip install -e ".[dev]"
```

Requires Poppler (`pdftoppm`, `pdfinfo`) and Tesseract 5 on PATH.

## Use

```
statementbridge classify    <pdf>                     # text layer or scan?
statementbridge audit       <pdf> --profile gramin_cc --expect
statementbridge parse       <pdf> --profile sbi_current --out rows.csv
statementbridge ocr-bakeoff <pdf> --profile gramin_cc --first 1 --last 3
statementbridge profiles
```

`audit` reports what a file actually contains — page counts, printed page
numbers, printed page totals, brought-forward balances — without assuming
anything. It is the first thing to run on a statement that misbehaves.

## How it works

Both sample PDFs are image-only 150 DPI scans with no text layer, so every
figure has to survive OCR. Accuracy therefore comes from **redundancy**, not
from character quality. A statement massively over-determines itself: N
transactions carry N amounts and N+1 balances, plus printed page totals and a
brought-forward figure on every page. The parser is a constraint solver over
that redundancy.

**One signed convention.** Credit positive, debit negative, everywhere inside
the pipeline. Direction always comes from `delta = balance[n] − balance[n−1]`,
never from which column a figure was printed in — on these scans column
position is the least reliable signal on the page. A cash-credit account whose
balance crosses zero needs no special case, and `Dr`/`Cr` is applied only at
export.

**Error localisation, not guesswork.** Where the printed amount and the balance
movement disagree, the question is which of the two is wrong:

| Signature | Diagnosis |
|---|---|
| Two adjacent conflicts | the balance they share is corrupt |
| One isolated conflict | the amount is corrupt |
| Delta implausible as a misread of the amount | a row was dropped — flagged, never invented |
| No single edit explains it | `UNRESOLVED`, sent to review |

Every repair must be reachable by a known glyph confusion, one dropped digit,
or a misread decimal point. Anything else goes to a human. An unresolved row
contains its own damage, so one real fault cannot manufacture a second
downstream.

**Export needs more than a tie.** A dropped row leaves the closing balance
untouched — its effect is absorbed into the neighbouring row's delta — so the
arithmetic can reconcile perfectly while a transaction is missing. Export
requires a paisa-exact tie *and* zero unresolved rows.

**Decimal throughout, never float.** The client's existing sample workbook
carries `3240.71999999997` and a `-2.77e-11` variance; here the variance is
exactly zero.

## Why the fixtures do not reconcile

Both scans are 150 DPI — half what Tesseract expects — and the Gramin ledger is
dot-matrix on top of that. Measured row agreement (printed amount matching the
balance movement) is about **38%** on Gramin and far lower on SBI. The repair
engine fixes isolated errors correctly, but its premise is that errors are
sparse; at this density conflicts are adjacent more often than isolated, and
which field is wrong becomes genuinely undecidable. It refuses to guess, which
is why rows land in `UNRESOLVED` rather than quietly wrong.

Rendering higher does not help, because interpolation cannot add detail the
capture never recorded:

| Render DPI | Row agreement |
|---|---|
| 300 | 45% |
| 450 | 21% |
| 600 | 11% |

**A 300–400 DPI optical rescan is the single change that would move this most.**

## Measurements behind the code

Every preprocessing choice here was measured on the fixtures, and most of the
obvious ones proved wrong:

- **The dot-matrix ledger is read best with no conditioning at all.** Rendering
  the bilevel source at 300 DPI already yields a clean antialiased upscale;
  re-binarising discards the greyscale edge information Tesseract was trained
  on. Otsu-plus-close scored 78 well-formed money tokens against 81 raw.
- **Deskewing destroys pages.** The angle estimator keys on dominant ink
  orientation, which these ledgers bias with full-width rules and a right-hand
  block of user-id columns. On Gramin page 3 it dropped row agreement from 38%
  to 0%. It is no longer applied blind.
- **The ruled table is the opposite case.** Shading defeats a global threshold,
  so Sauvola plus rule removal lifts money tokens from 18 to 41 per page.
- **SBI rows span several printed lines** — dates, amounts and reference each on
  their own — so they are assembled by ruled row band, not by text line. Before
  that, the page produced no usable rows at all.
- **Row assembly was not the bottleneck it looked like** on Gramin: word
  clustering and Tesseract's own line grouping score identically there.

## Page counts

The Gramin statement is **27 printed pages across 24 scanned sheets** — the
continuous stationery was scanned with more than one printed page landing on
some sheets. Nothing is missing from the file. `statementbridge audit` reports
this from the statement's own running headers.

## OCR engine comparison

Tesseract is the default. PaddleOCR is implemented behind the same Protocol
(`statementbridge.ocr.paddle`) and installs via the `paddle` extra, but **could
not be benchmarked here: it downloads its recognition models on first use and
had no network access.** That is worth weighing for an offline deployment — the
models would have to be pre-bundled and pinned, on top of roughly 2GB of
PaddlePaddle. Tesseract needs about 100MB and ships offline.

Measured, Tesseract only:

| Fixture | Rows | Row agreement | Time |
|---|---|---|---|
| Gramin, pages 1–3 | 122 | 37.8% | 15s |
| SBI, pages 3–4 | 21 | 5.3% | 22s |

## Tests

```
pytest                    # everything
pytest -m "not slow"      # skip the full-document OCR runs
pytest -m slow            # fixture regressions
```

Fixtures live in the `Ba-resources` repository and are located automatically
from a sibling checkout, or via `SB_FIXTURE_DIR`. Tests skip cleanly when they
are absent.

The regression tests **pin current behaviour rather than assert the acceptance
bar**, since the bar is not met. Their thresholds are floors to defend against
regression, not targets that have been hit. Raise them when rescans arrive.
