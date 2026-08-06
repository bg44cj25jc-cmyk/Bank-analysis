# The rules engine

Turning a narration into an accounting decision: a category, a Tally ledger and
a contra flag.

Extraction answers *what the bank printed*. This answers *what it meant*. It runs
after the balance chain has settled, over rows whose direction is already known,
and it decides nothing about money — only about where that money should be
posted.

## The taxonomy

35 codes. Thirty-three are transcribed from the `Category Summary` sheet of the
client's own migration workbook, descriptions included, because the firm already
reads and checks statements against that sheet; a classifier that renamed the
categories would produce output nobody could reconcile against work they had
already done.

**`RTGS_IN` and `RTGS_OUT` are ours.** The client's savings account never used
the rail, so their sheet has no row for it; a current account uses it constantly,
and the nearest code available says NEFT. Labelling a wire transfer as a
different rail would have bought an identical-looking sheet with a quiet error in
the one field the category exists to state.

Run `statementbridge categories` to print the taxonomy with its ledgers.

Each code carries:

- **a ledger template**, because the workbook's self-transfer ledger reads
  `Ajoy Nag - Own Accounts (Contra)` — the account holder's name is part of it.
  The holder is confirmed by a human at the header gate and travels with the job.
  An account whose holder was never confirmed renders `Account Holder`, which
  reads as a gap rather than as a name;
- **a contra flag**, because a contra voucher is a different posting in Tally,
  not a different label. Money moving between the client's own bank and cash, or
  between two of their own accounts, is not income or expenditure and must not
  reach a profit and loss account;
- **a direction constraint**. Bank charges are always a debit, salary always a
  credit. A rule that contradicts its category is rejected when the pack is
  built, because that fault is invisible in output — a credit posted to an
  expense ledger looks like a number, not like an error.

## Writing a rule

A rule is data, as a bank profile is:

```python
Rule(id="upi.in", category=C.UPI_IN, words=("upi",), direction=CREDIT)
Rule(id="charges.sms", category=C.BANK_CHARGES, words=("sms", "alert"), direction=DEBIT)
Rule(id="self.holder-name", category=C.SELF_TRANSFER, predicate="holder_name", review=True)
```

Every word must appear, in any order. `ledger=` overrides the category's default
where a payer is known precisely enough to deserve its own ledger. `review=True`
marks matched rows for human attention without withholding the answer.
`predicate=` names a structural test for narrations recognisable by shape rather
than vocabulary — `184693 DHARMANAGAR` is a branch deposit but contains no word
saying so.

### How a word is matched

Narrations are normalised first: split on punctuation, then each token judged.
Pure digit runs are kept as numbers, mixed tokens that are mostly digits and six
characters or longer are dropped as references, and the rest become words
canonicalised through the OCR glyph table in `parse/rowkind.py`. So `G5T` and
`GST` are the same string before any comparison happens.

A rule word then matches by, in order: exact word, prefix (words of 6+
characters), or a fuzzy ratio of 85 (words of 5+ characters). Short words must
match exactly — `fuzz.partial_ratio` of `upi` against a long narration is close
to a coin toss.

Prefix matching exists because rails disagree about spaces. The same aggregator
arrives as `PHONEPE LIMITED` over NEFT and `PHONEPELIMITEDPAYMENTAGGREGATORE`
over IMPS.

### Order is the priority

First match wins. The pack runs specific to general, in seven bands: the holder's
own name, reversals, the bank's own entries, cash, the accounting vocabulary,
cheques, and **the rails last**. A rail says how money moved and almost nothing
about what it was for, so it is the weakest true statement available and nothing
should ever lose to one.

Four orderings are load-bearing, and each is there because the obvious
arrangement was wrong:

| Ordering | Why |
|---|---|
| Holder name above everything | `WTHDRL LOAN EMI … -AJOY NAG DRAWDOWN` is a drawdown, not an EMI. What the money *is* outranks the rail it took. |
| Reversals above the rails | A reversed payment classified as an ordinary receipt leaves both it and the original in sundry, overstating turnover by twice the amount. |
| Interest above charges | The fuzzy matcher reaches `CHARGED` from `charge`, so `INTEREST CHARGED ON CC` would land in bank charges. |
| Charges above the rails | `Charges for NEFT` is the bank's fee on a transfer, not the transfer. |

Two absences are also deliberate. **No rule matches `CR` or `DR`** — direction
comes from the balance movement, which every neighbouring row and printed page
total checks, while the token is one more thing a 150 DPI recogniser can drop.
And **there is no rule on the bare word `SELF`**: it reads like a self-transfer
marker and is not one, since `CASH DEP-SELF-…` is a deposit made at the counter.
Both are contra, so the error would have survived reconciliation and landed in
the wrong ledger anyway.

`FD` and `RD` are spelled out rather than abbreviated. Two-character words must
match exactly, and canonicalisation maps `3RD` onto `rd` — an ordinal in an
address would have opened a term deposit.

## What it refuses to decide

Nothing matched means `UNCLASSIFIED`, a suspense ledger and no rule id — the same
posture `RowState.UNRESOLVED` takes towards money it cannot explain. An
unclassified row is cheap: someone reads it once. A row confidently posted to the
wrong ledger is not, because nothing downstream will ever question it again.

Unclassified rows do **not** block export. Export is blocked by money that does
not reconcile; an unlabelled row is a posting decision a human has yet to make,
and it is reported as a count instead.

## The summary must tie

The category summary carries one line per category — including the empty ones,
which are the checklist showing a category was considered and found absent — and
**it must agree with the balance chain to the paisa**. Every settled row belongs
to exactly one category, so the category credits have to sum to the chain's
credits and the debits to its debits. That is the same redundancy argument the
balance engine runs on, one level up.

`statementbridge categorise` exits non-zero when it does not tie.

Note what this does not claim. Ties prove the *arithmetic* of the classification,
never its correctness: a statement in which every row is unclassified ties
perfectly. Labels are counted separately and read by a person.

## How good is it?

Measured against the 236 rows of the client's workbook that a person categorised
by hand: **236/236 categories, 236/236 ledgers, 236/236 contra flags** — with one
deliberate, documented divergence on 5 rows where the sheet gives PhonePe's NEFT
settlements their own ledger and leaves its IMPS ones generic.

That corpus exercises **10 of 35 categories and 11 of 76 rules**: one savings
account, one year, with no ATM withdrawal, no salary, no cheque paid and no
utility bill in it. A second labelled statement is worth more here than any
further work on this one.

`pytest -m fixtures tests/regression/test_ledger_corpus.py` re-runs it. Unlike
the OCR regressions, those thresholds are **exact rather than floors**: nothing
here touches a recogniser, so the same input gives the same answer on every
machine, and a floor would only hide the day a rule change silently reclassified
a row.
