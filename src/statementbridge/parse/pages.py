"""Turn one page's assembled lines into rows and anchors.

This is the point where the two parser families converge. Up to here they are
completely different machines -- one rasterises and recognises, the other reads
a text layer straight off the page -- and from here they are identical: the same
trap classifier, the same field extraction, the same anchors, the same frame.

It lived in duplicate in ``scanned`` and ``digital`` for as long as a document
was assumed to be entirely one or entirely the other. It is shared now because
that assumption does not hold: a branch that staples a rescanned sheet into an
otherwise digital export produces a document that needs both families, page by
page, and interleaving them is only possible if what happens *after* row
assembly is one piece of code rather than two copies of it.

Nothing here decides anything about extraction that the two copies did not
already decide identically.
"""

from __future__ import annotations

from typing import Any, Sequence

from ..ocr.engine import OcrLine
from .frame import Anchor, Txn
from .lineparse import build_txn
from .profiles.base import BankProfile
from .rowkind import RowKind, classify_line

#: How far down the page the closing block must appear before it is believed.
#:
#: The Gramin ledger ends with a Limits / Draw Power / Int Rate table, after
#: which nothing on the page is transactional. But a narration that merely
#: mentions an interest rate would otherwise truncate an entire sheet, so the
#: signal is only trusted in the lower part of the page.
LIMITS_FROM = 0.6


def read_page(
    lines: Sequence[OcrLine],
    profile: BankProfile,
    *,
    page_no: int,
    start_row: int,
    printed_page_pattern,
) -> tuple[list[Txn], list[Anchor], dict[str, Any]]:
    """Classify every line on a page, and keep the ones that carry money.

    Confidence is taken from the line itself and needs no special case per
    family: a text layer is exact, so the digital family builds its words at
    100% and the mean simply comes out at 100.
    """
    rows: list[Txn] = []
    anchors: list[Anchor] = []
    printed_pages: set[int] = set()
    confidences: list[float] = []
    limits_reached = False
    dropped = 0

    for offset, line in enumerate(lines):
        source_row = start_row + offset
        text = line.text
        confidences.append(line.confidence)

        page_match = printed_page_pattern.search(text)
        if page_match:
            printed_pages.add(int(page_match.group(1)))

        classification = classify_line(
            text,
            page_no=page_no,
            source_row=source_row,
            extra_patterns=profile.patterns(),
        )

        if classification.anchor is not None:
            anchors.append(classification.anchor)

        if classification.kind is RowKind.LIMITS_TABLE:
            if offset > len(lines) * LIMITS_FROM:
                limits_reached = True
            continue

        if limits_reached or not classification.kind.is_transaction:
            continue

        row = build_txn(
            text,
            page_no=page_no,
            source_row=source_row,
            is_overdraft=profile.is_overdraft,
        )
        if row is None:
            dropped += 1
            continue
        row.ocr_confidence = line.confidence
        rows.append(row)

    diagnostics = {
        "page_no": page_no,
        "printed_pages": sorted(printed_pages),
        "lines": len(lines),
        "rows": len(rows),
        "unparsed_lines": dropped,
        "mean_confidence": (
            round(sum(confidences) / len(confidences), 1) if confidences else 0.0
        ),
    }
    return rows, anchors, diagnostics
