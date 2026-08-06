# StatementBridge

Converts Indian bank statement PDFs into Tally-ready output for one financial
year. Offline by default: nothing leaves the machine.

Built for SuhagKuti Tax & Legal Services. **Parser core, the service layer —
CLI, HTTP API and a worker queue — and the rules engine that turns a narration
into an accounting decision.**

## Status

Phase 1 is built and does not yet meet its acceptance bar. The extraction path
runs end to end on both sample statements, and the balance engine is complete
and tested, but the fixtures do not reconcile. The cause is measured and is not
a software defect — see [Why the fixtures do not reconcile](#why-the-fixtures-do-not-reconcile).

[docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md) is the fuller picture: the phase
roadmap, what each step delivered, and what phase 5 needs from here.

| Component | State |
|---|---|
| Decimal / Indian money handling | done |
| Trap and row classifier | done |
| Balance chain and repair engine | done |
| OCR pipeline (dot-matrix and ruled-table) | done |
| Digital-text parser (pdfplumber) | done, synthetic tests only |
| Bank profiles, audit and CLI | done |
| Upload capture-quality gate and scanning SOP | done |
| Per-page routing between the two parser families | done |
| FastAPI service, job queue and worker | done |
| Rules engine: categories, Tally ledgers, contra, category summary | done |
| Excel, GUI, Tally XML, Ollama | not started (Phases 5–8) |

## Install

```
pip install -e ".[dev]"
```

Requires Poppler (`pdftoppm`, `pdfinfo`) and Tesseract 5 on PATH.

## Use

```
statementbridge quality     <pdf>                     # is this scan worth processing?
statementbridge classify    <pdf>                     # text layer or scan?
statementbridge audit       <pdf> --profile gramin_cc --expect
statementbridge parse       <pdf> --profile sbi_current --out rows.csv
statementbridge categorise  <pdf> --profile gramin_cc --holder "AJOY NAG"
statementbridge ocr-bakeoff <pdf> --profile gramin_cc --first 1 --last 3
statementbridge profiles
statementbridge categories
```

`quality` grades the capture before anything expensive happens, and names the
scanner setting to change. Run it first. It exits 2 on `REJECT`, so a script can
gate on it, and `--no-render` restricts it to the structural checks — which need
neither Poppler nor Tesseract and settle a sixty-page file in about a third of a
second. See [docs/SCANNING_SOP.md](docs/SCANNING_SOP.md) for the office-facing
one-pager.

`audit` reports what a file actually contains — page counts, printed page
numbers, printed page totals, brought-forward balances — without assuming
anything. It is the first thing to run on a statement that misbehaves.

## Running it as a service

```
pip install -e ".[api]"
cp docker/.env.example docker/.env      # set SB_WORKER_TOKEN
docker compose -f docker/compose.yml up -d
```

Two containers from one image: `api` serves the browsers, `worker` does the
recognising. A statement is uploaded, graded, read for its account header,
confirmed by a person, then parsed.

**The worker never opens the database.** It claims jobs and reports results over
HTTP, which is the whole reason the deployment can start on one machine and grow
to two without being rewritten — running OCR on a faster desktop instead means
starting the same worker there with `SB_API_URL` pointing back at the NAS, and
nothing in the code knows the difference. `docker/compose.desktop.yml` is that
second machine. When it is off, jobs simply queue.

Measured footprints, so the budget is not guesswork:

| Process | Steady | Peak |
|---|---|---|
| `api` | 150 MB | 150 MB (flat over 100 reads and four 17 MB uploads) |
| `worker`, dot-matrix page | 105 MB | 129 MB |
| `worker`, ruled table (Sauvola) | 176 MB | **397 MB** |
| `tesseract` subprocess | — | 124 MB (separate process; add it) |

So roughly **520 MB per concurrent worker at peak**, and the binding constraint
on a four-core NAS turns out to be cores rather than memory.

The image **asserts** its Tesseract major.minor at build time rather than pinning
an exact Debian revision. Row agreement moves between recogniser versions — 37.8%
against 45.5% on the same fixture — so an engine that drifted would silently
re-baseline the numbers that decide whether a rescan helped, while an exact pin
would break the build every time Debian issues a security update.

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

**A narration is turned into a posting, or into a question.** Every settled row
gets a category, a Tally ledger, a contra flag and the id of the rule that
decided it. Rules are data and ordered specific-to-general, with the payment
rails last: a rail says how money moved and almost nothing about what it was
for. Nothing matched means `UNCLASSIFIED` and a suspense ledger, never a nearby
guess — an unclassified row is read once by a person, while a row confidently
posted to the wrong ledger is never questioned again. The resulting category
summary must tie to the balance chain to the paisa. See
[docs/RULES.md](docs/RULES.md).

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

### What the scanner actually recorded

Read off the PDF object structure — image dimensions against the rectangle they
are placed into, so this is the capture itself and not an inference from it:

| Fixture | Sheets | Source pixels | Depth | Codec | Effective DPI |
|---|---|---|---|---|---|
| Gramin CC | 24 | ~1242×1731 | **1-bit bilevel** | CCITT G4 | **150 × 150** |
| SBI Current | 60 | ~1244×1731 | 8-bit RGB | **JPEG, lossy** | **150 × 150** |

The Gramin figure is the worse of the two and was not previously called out:
the ledger is **1-bit**, so the greyscale edge information the recogniser was
trained on was discarded *by the scanner*, before the file was written. That is
the signature of a Text/Fax/Black-and-White preset. `preprocess.prepare()` is
right to refuse to re-binarise it, but there is nothing left in the file to
recover. SBI's lossy colour is waste rather than damage — it is what makes a
60-page statement 17MB — but it softens digit edges for no gain.

Both are exactly what `docs/SCANNING_SOP.md` prevents, and `statementbridge
quality` now reports them in about a third of a second, at upload, instead of
twenty minutes into a job that could not have reconciled.

Every Gramin sheet also carries a `/Rotate`, alternating 90 and 270. Dividing
pixels by points naively gives 108 × 208 DPI — non-square pixels, which no
scanner produces — so the gate tries both axis pairings and takes the
self-consistent one.

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

The extraction regression tests **pin current behaviour rather than assert the
acceptance bar**, since the bar is not met. Their thresholds are floors to defend
against regression, not targets that have been hit. Raise them when rescans
arrive.

The rules-engine regression is the opposite and deliberately so. It replays the
236 rows of the client's migration workbook that a person categorised by hand,
and asserts **exact** agreement — 236/236 on category, Tally ledger and contra
alike. Nothing on that path touches a recogniser, so the same input gives the
same answer on every machine, and a floor would only hide the day a rule change
silently reclassified a row. What it does not prove is scope: that corpus
exercises ten of the thirty-five categories, and a second labelled statement
would be worth more than any further work on this one.
