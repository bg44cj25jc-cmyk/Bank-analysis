# Project status and handoff

Living document. Update it at each gate. It exists so a fresh session — or a
different person — can pick this up without the conversation that produced it.

**Last updated:** step 4 in progress (category catalogue landed, rules engine next).

---

## Where things live

| Repo | Contents |
|---|---|
| `Bank-analysis` | the application. Work on branch `claude/statementbridge-phase1-deploy-90x5ep` |
| `Ba-resources` | the two 150 DPI fixtures, the target workbook, the UI prototype |
| `Bank-analysis-extra-sample` | **empty.** Where rescans and the Bandhan PDF should go |

Fixtures are found automatically from a sibling checkout, or via `SB_FIXTURE_DIR`.
Tests that need them skip cleanly when absent.

## Build order and status

| # | Step | State |
|---|---|---|
| 1 | Read the repo, re-benchmark, report | ✅ done — see [Measurements](#measurements-do-not-re-derive-these) |
| 2 | Upload quality gate + scanning SOP | ✅ merged (`85bb6da`) |
| 3 | FastAPI, Docker Compose, worker queue | ✅ merged (`e14cc4a`) |
| 4 | Rules engine + category assignment | 🔨 **in progress** |
| 5 | Excel export, format-matched to the sample | not started |
| 6 | React PWA — desktop first, then touch review | not started |
| 7 | Learning loop, metrics, roles, audit | not started |
| 8 | Tally XML | not started |
| 9 | Local model fallback | **probably unnecessary** — see below |
| 10 | Camera capture | only if paper statements turn out to be common |

Steps 1–3 merged via PR #2. A merged PR cannot track new work: restart the
branch from `main` before starting a new step —
`git fetch origin main && git checkout -B <branch> origin/main`.

## Decisions taken (do not re-litigate)

1. **Proceed without the rescans**; benchmark when they arrive.
2. **The export target is a digital statement.** The Bandhan PDF behind the
   sample workbook has a text layer and runs through `parse/digital.py`, never
   OCR. That module is the least-proven in the repo — its own docstring says it
   has never seen a real bank statement.
3. **PWA is English-only for v1.** The prototype's Bengali is out of scope.
4. **Queue is SQLite (WAL), owned solely by the API.** The worker is an HTTP
   client and never opens the database — that is what keeps moving OCR to the
   desktop a compose change rather than a migration.
5. **Auth is a skeleton in step 3, enforced in step 7.** Roles and the
   append-only audit table exist and are wired now.
6. **Stirling-PDF goes on the desktop tier only** (`docker/compose.desktop.yml`),
   for the office's own PDF work. In-pipeline operations use **pikepdf**, which
   covers split, rotate, merge, decrypt *and* repair in-process.
7. **Header OCR-tolerance deferred** until rescans land.
8. **Self-match beats everything** in classification: it beats purpose keywords
   (`WTHDRL LOAN EMI … -AJOY NAG DRAWDOWN` is F, not O) and beats the reversal
   rule (`UPI/REV/AJOY NAG/PUNB` is F, not Y). **Y is therefore reserved for
   reversals of third-party transactions.** The assumption is logged.
9. **Ambiguous rows stay UNCLASSIFIED.** The nine `184693 DHARMANAGAR` credits
   get no rule; the client's own ledger for them says "Suspense - verify".
10. **Single-tier deployment** on the DS925+ with **16 GB minimum**.

## Measurements (do not re-derive these)

**Capture — read off PDF structure, no rendering:**

| Fixture | Sheets | Depth | Codec | Effective DPI |
|---|---|---|---|---|
| Gramin CC | 24 | **1-bit bilevel** | CCITT G4 | 150 × 150 |
| SBI Current | 60 | 8-bit RGB | JPEG, lossy | 150 × 150 |

Gramin sheets carry a `/Rotate` alternating 90/270; naive px÷pt gives a bogus
108 × 208, so the gate tries both axis pairings and takes the self-consistent one.

**Extraction baseline — Tesseract 5.3.4.** Gramin p1–3: **122 rows, 45.5%**.
SBI p3–4: **20 rows, 10.5%**. These do **not** match the original README (37.8% /
5.3%) because row agreement moves between Tesseract versions. **Pin the engine
before benchmarking rescans** or the comparison is against a moving baseline —
the Docker image asserts its major.minor for this reason.

**Speed:** 6.2 s/page Gramin, 11.9 s/page SBI on a 4-core Xeon @2.8 GHz. The
DS925+ is roughly 1.6× slower per core. The prototype's *"24 pages ≈ 40 seconds"*
is **not reachable on the NAS** at any worker count.

**Memory — measured, not estimated:**

| Process | Steady | Peak |
|---|---|---|
| `api` | 150 MB | 150 MB |
| `worker`, dot-matrix | 105 MB | 129 MB |
| `worker`, ruled table (Sauvola) | 176 MB | 397 MB |
| `tesseract` subprocess | — | 124 MB (separate process, additive) |

≈ **520 MB per concurrent worker.** Whole stack ≈ 5 GB. 4 GB cannot run this;
16 GB is the floor. **The binding constraint is cores, not memory.**

**Classification dry-run** against the workbook's 236 labelled rows:
**227 auto-classified (96.2%), zero disagreements, 9 UNCLASSIFIED (3.8%)**.
Caveat: the ladder was designed after seeing those labels, so treat it as an
upper bound. Only 10 of 33 categories appear in that statement.

⇒ **Step 9's local model looks unnecessary.** Confirm on a second statement.

## Outstanding / blocked

- **The Docker image has never been built.** No daemon has been available in any
  session. `docker compose config` validates both files, but that is YAML only.
  **This is the top item for anyone with Docker.**
- **No CI.** The ~170 tests have only ever run locally. `pytest -m "not slow"`
  gives 150 passed / 9 skipped without fixtures. Note that `Ba-resources` holds
  **real client bank statements** — do not wire it into a hosted CI runner.
- **Waiting on the firm**, in priority order:
  1. **The Bandhan PDF** — it is the export target and exercises the
     least-proven module.
  2. **300 and 400 DPI greyscale rescans** of both fixtures → then re-run and
     compare against the control totals in `cli.py`.
- 23 of the 33 categories have **no example anywhere** — their rules will be
  written but unverified until more statements arrive.

## How to pick this up in a new session

1. Read this file, then `README.md`.
2. `git fetch origin main && git checkout -B claude/statementbridge-phase1-deploy-90x5ep origin/main`
3. `pip install -e ".[dev,api]"`; you need Poppler and Tesseract 5 on PATH.
4. `pytest -m "not slow"` should be green.
5. Continue at the first step above marked not-done, and **stop at each gate for
   review** — that is how this project is run.

## Principles that are not up for renegotiation

- Signed convention throughout: credit positive, debit negative. Direction comes
  from `delta = balance[n] − balance[n−1]`, **never** from column position.
- `Decimal` everywhere, never float. Money crosses HTTP as **strings** and is
  stored in **TEXT** columns.
- Per-page digital-vs-scanned classification.
- Bank profiles are data, not branches in the extraction code.
- Error localisation: adjacent conflicts mean a corrupt balance, isolated
  conflicts a corrupt amount, anything else `UNRESOLVED` and a human decides.
- Export needs a paisa-exact tie **and** zero unresolved rows. A dropped row
  leaves the endpoints untouched, so arithmetic alone can tie while a
  transaction is missing.
- Never guess a transaction. Ambiguous → `UNCLASSIFIED`, damaged → `UNRESOLVED`.
- Never round to whole rupees. Never raise a regression threshold to make a test
  pass.
- Rules first, model second, human last. **The model never overrules a rule.**
- No mobile upload or export flow. Upload and export are desktop-only.
- Client data does not leave the premises.
