"""Error localisation over the balance chain.

At 150 DPI on dot-matrix, individual characters cannot be trusted. What *can*
be trusted is that the statement is massively over-determined: N transactions
carry N amounts and N+1 balances, and every amount is checked twice over by its
neighbours. Where the printed amount and the balance movement disagree, the
question is not "what should this number be" but "which of the two is wrong" --
an error-localisation problem with a decidable answer most of the time.

The signatures the engine reasons from:

======================================  ==========================  =========================
Observation                             Diagnosis                   Repair
======================================  ==========================  =========================
one isolated conflict, next row agrees  the amount is corrupt       amount := |delta|
two adjacent conflicts                  the shared balance is       balance := prev + amount,
                                        corrupt                     confirmed by the next row
conflict, |delta| implausible as an     a row was dropped by OCR    flag, never fabricate
OCR corruption of the amount
no single edit explains it              ambiguous                   UNRESOLVED, sent to review
======================================  ==========================  =========================

Every candidate repair must also be *OCR-plausible*: a fix reachable by a
known glyph confusion or a misread decimal point is applied automatically, one
that requires inventing digits is refused and the row goes to a human. That is
the line between correcting a scan and guessing a transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from rapidfuzz.distance import Levenshtein

from ..money import ZERO, q2
from ..parse.frame import RowState, Txn
from .chain import ChainReport, apply_directions, summarise

#: Factors that a misplaced or missed decimal separator produces.
_SEPARATOR_FACTORS: tuple[Decimal, ...] = (
    Decimal(10), Decimal(100), Decimal("0.1"), Decimal("0.01"),
)


@dataclass(slots=True)
class Diagnosis:
    index: int
    kind: str          # AMOUNT_CORRUPT | BALANCE_CORRUPT | AMOUNT_MISSING |
                       # BALANCE_MISSING | MISSING_ROW | AMBIGUOUS
    detail: str
    applied: bool
    page_no: int = 0


def _digits(value: Decimal) -> str:
    return f"{abs(q2(value)):.2f}".replace(".", "")


def ocr_plausible(observed: Decimal | None, candidate: Decimal) -> bool:
    """Could ``candidate`` have been scanned as ``observed``?

    Accepts a couple of substituted glyphs, one dropped or inserted digit, or a
    decimal point read in the wrong place. Rejects anything that would require
    the OCR to have invented an unrelated number -- which is the signal that
    something structural went wrong, such as a dropped row.
    """
    if observed is None:
        return True  # nothing was read at all; no evidence either way
    observed_digits, candidate_digits = _digits(observed), _digits(candidate)
    if observed_digits == candidate_digits:
        return True
    if observed != 0:
        for factor in _SEPARATOR_FACTORS:
            if q2(abs(observed) * factor) == q2(abs(candidate)):
                return True
    distance = Levenshtein.distance(observed_digits, candidate_digits)
    length_gap = abs(len(observed_digits) - len(candidate_digits))
    if length_gap == 0:
        return distance <= 2
    if length_gap == 1:
        return distance <= 1
    return False


class _Chain:
    """Mutable view of the chain during repair."""

    def __init__(self, rows: list[Txn], opening: Decimal) -> None:
        self.rows = rows
        self.opening = q2(opening)

    def balance(self, index: int) -> Decimal | None:
        if index < 0:
            return self.opening
        return self.rows[index].balance

    def amount(self, index: int) -> Decimal | None:
        return self.rows[index].printed_amount

    def delta(self, index: int) -> Decimal | None:
        current, previous = self.balance(index), self.balance(index - 1)
        if current is None or previous is None:
            return None
        return q2(current - previous)

    def consistent(self, index: int) -> bool:
        if index < 0 or index >= len(self.rows):
            return True  # off the ends, nothing to contradict
        delta, amount = self.delta(index), self.amount(index)
        if delta is None or amount is None:
            return False
        return abs(delta) == q2(abs(amount))


def resolve(
    rows: list[Txn], opening: Decimal, *, closing: Decimal | None = None
) -> list[Diagnosis]:
    """Localise and repair chain conflicts in place."""
    diagnoses: list[Diagnosis] = []
    if not rows:
        return diagnoses

    chain = _Chain(rows, opening)
    count = len(rows)
    broken = False  # an unrepaired row upstream invalidates the deltas after it

    for index in range(count):
        if chain.consistent(index):
            broken = False  # the chain has re-established itself
            continue

        row = rows[index]
        diagnosis = _diagnose(chain, index, closing, broken)
        diagnoses.append(diagnosis)
        _mark(row, diagnosis)
        broken = not diagnosis.applied

        if diagnosis.kind == "BALANCE_CORRUPT" and index + 1 < count:
            # Correcting a balance also settles the row that follows it: its
            # delta was wrong only because the balance it measured from was.
            rows[index + 1].row_state = RowState.REPAIRED
            rows[index + 1].note("balance of preceding row corrected")

    return diagnoses


def _diagnose(
    chain: _Chain, index: int, closing: Decimal | None, broken: bool
) -> Diagnosis:
    """Work out which field is wrong on one inconsistent row."""
    rows = chain.rows
    row = rows[index]
    previous_balance = chain.balance(index - 1)
    amount = chain.amount(index)
    balance = chain.balance(index)

    # --- containment: do not blame a row for an upstream break ----------
    # If the previous row could not be resolved, this row's delta was measured
    # from a balance we already know to be untrustworthy. Diagnosing it
    # independently would manufacture a second, fictitious fault -- typically a
    # bogus "missing row" -- from a single real one. The damage is held here
    # until a consistent row (or a page anchor) re-establishes the chain.
    if broken or previous_balance is None:
        return Diagnosis(
            index, "UPSTREAM_BREAK",
            "delta unreliable: the preceding row is unresolved", False, row.page_no,
        )

    # --- a balance the OCR could not read at all ------------------------
    if balance is None:
        return _repair_missing_balance(chain, index, closing)

    # --- an amount the OCR could not read at all ------------------------
    if amount is None:
        delta = chain.delta(index)
        if delta is None:
            return Diagnosis(index, "AMBIGUOUS",
                             "neither amount nor balance legible", False, row.page_no)
        row.printed_amount = q2(abs(delta))
        return Diagnosis(index, "AMOUNT_MISSING",
                         "amount recovered from balance delta", True, row.page_no)

    delta = chain.delta(index)
    if delta is None:
        return Diagnosis(index, "AMBIGUOUS", "balance movement undeterminable",
                         False, row.page_no)

    is_last = index == len(rows) - 1
    if is_last:
        return _repair_last(chain, index, delta, amount, closing)

    # If this balance were wrong, the next row's delta would be wrong too.
    # It is not, so the balance stands and the printed amount is the suspect.
    if chain.consistent(index + 1):
        return _repair_amount(chain, index, delta, amount)

    # Two adjacent conflicts: blame the balance they share.
    return _repair_balance(chain, index)


def _repair_amount(
    chain: _Chain, index: int, delta: Decimal, amount: Decimal
) -> Diagnosis:
    row = chain.rows[index]
    candidate = q2(abs(delta))
    if ocr_plausible(amount, candidate):
        row.printed_amount = candidate
        return Diagnosis(
            index, "AMOUNT_CORRUPT",
            f"amount {amount} -> {candidate} from balance delta", True, row.page_no,
        )
    # The delta is nothing like the printed amount. The likeliest structural
    # explanation is that OCR lost a row here. We report where, and how much is
    # unaccounted for, but we do not invent the transaction.
    #
    # This row's own direction is unknown -- that is exactly what the broken
    # delta would have told us -- so the gap is one of two values depending on
    # whether this row is a debit or a credit. Both are reported; picking one
    # would be a guess.
    candidates = sorted(
        {abs(q2(delta - sign * abs(amount))) for sign in (Decimal(1), Decimal(-1))}
        - {ZERO}
    )
    if candidates:
        gap = " or ".join(str(value) for value in candidates)
        return Diagnosis(
            index, "MISSING_ROW",
            f"balance moves {delta} but this row shows {amount}; "
            f"a transaction of {gap} appears to be missing before this row",
            False, row.page_no,
        )
    return Diagnosis(index, "AMBIGUOUS", "amount and delta irreconcilable", False, row.page_no)


def _repair_balance(chain: _Chain, index: int) -> Diagnosis:
    """Two adjacent conflicts: recompute the shared balance, confirm with the next row."""
    row = chain.rows[index]
    previous_balance = chain.balance(index - 1)
    amount = chain.amount(index)
    next_amount = chain.amount(index + 1)
    next_balance = chain.balance(index + 1)
    observed = chain.balance(index)

    if previous_balance is None or amount is None:
        return Diagnosis(index, "AMBIGUOUS", "insufficient context to repair balance",
                         False, row.page_no)

    candidates: list[Decimal] = []
    for sign in (Decimal(1), Decimal(-1)):
        candidate = q2(previous_balance + sign * abs(amount))
        if next_amount is not None and next_balance is not None:
            if abs(q2(next_balance - candidate)) != q2(abs(next_amount)):
                continue  # the following row refuses this reading
        if candidate not in candidates:
            candidates.append(candidate)

    if not candidates:
        return Diagnosis(index, "AMBIGUOUS",
                         "no balance value satisfies both neighbouring rows",
                         False, row.page_no)

    if len(candidates) > 1:
        plausible = [c for c in candidates if ocr_plausible(observed, c)]
        if len(plausible) != 1:
            return Diagnosis(
                index, "AMBIGUOUS",
                f"balance could be either {' or '.join(str(c) for c in candidates)}",
                False, row.page_no,
            )
        candidates = plausible

    chosen = candidates[0]
    row.balance = chosen
    return Diagnosis(
        index, "BALANCE_CORRUPT",
        f"balance {observed} -> {chosen}, confirmed by the following row",
        True, row.page_no,
    )


def _repair_last(
    chain: _Chain, index: int, delta: Decimal, amount: Decimal, closing: Decimal | None
) -> Diagnosis:
    """The final row has no successor, so the printed closing is the only referee."""
    row = chain.rows[index]
    previous_balance = chain.balance(index - 1)
    balance = chain.balance(index)

    if closing is not None and balance is not None and previous_balance is not None:
        if balance == closing:
            row.printed_amount = q2(abs(delta))
            return Diagnosis(index, "AMOUNT_CORRUPT",
                             f"amount {amount} -> {abs(delta)}; balance matches printed closing",
                             True, row.page_no)
        for sign in (Decimal(1), Decimal(-1)):
            if q2(previous_balance + sign * abs(amount)) == closing:
                row.balance = closing
                return Diagnosis(index, "BALANCE_CORRUPT",
                                 f"balance {balance} -> {closing} from printed closing",
                                 True, row.page_no)
    return Diagnosis(index, "AMBIGUOUS",
                     "final row disagrees and no printed closing resolves it",
                     False, row.page_no)


def _repair_missing_balance(
    chain: _Chain, index: int, closing: Decimal | None
) -> Diagnosis:
    """Interpolate a balance the scan lost, if the neighbours pin it down."""
    row = chain.rows[index]
    previous_balance = chain.balance(index - 1)
    amount = chain.amount(index)
    next_balance = chain.balance(index + 1) if index + 1 < len(chain.rows) else closing
    next_amount = chain.amount(index + 1) if index + 1 < len(chain.rows) else None

    if previous_balance is None or amount is None:
        return Diagnosis(index, "BALANCE_MISSING",
                         "balance illegible and cannot be interpolated", False, row.page_no)

    candidates = []
    for sign in (Decimal(1), Decimal(-1)):
        candidate = q2(previous_balance + sign * abs(amount))
        if next_balance is not None:
            if next_amount is not None:
                if abs(q2(next_balance - candidate)) != q2(abs(next_amount)):
                    continue
            elif candidate != next_balance:
                continue
        candidates.append(candidate)

    if len(candidates) == 1:
        row.balance = candidates[0]
        return Diagnosis(index, "BALANCE_MISSING",
                         f"balance interpolated as {candidates[0]}", True, row.page_no)
    return Diagnosis(index, "BALANCE_MISSING",
                     "balance illegible; neighbours do not determine it uniquely",
                     False, row.page_no)


def _mark(row: Txn, diagnosis: Diagnosis) -> None:
    if diagnosis.applied:
        row.row_state = RowState.REPAIRED
    else:
        row.row_state = RowState.UNRESOLVED
    row.note(diagnosis.detail)


def settle(
    rows: list[Txn],
    opening: Decimal,
    *,
    closing: Decimal | None = None,
) -> tuple[ChainReport, list[Diagnosis]]:
    """Repair what can be repaired, then derive every direction from the chain."""
    diagnoses = resolve(rows, opening, closing=closing)
    apply_directions(rows, opening)

    # Rows still unresolved must not silently contribute a fabricated figure.
    for row in rows:
        if row.row_state is RowState.UNRESOLVED and row.balance is None:
            row.debit = row.credit = ZERO

    report = summarise(rows, opening, closing)
    for diagnosis in diagnoses:
        if not diagnosis.applied:
            report.notes.append(
                f"row {diagnosis.index} (page {diagnosis.page_no}): "
                f"{diagnosis.kind} - {diagnosis.detail}"
            )
    return report, diagnoses
