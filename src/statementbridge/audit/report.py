"""Evidence report for a statement PDF.

Written to answer questions about a source file without assuming anything about
it. The immediate case is the Gramin fixture, described as 27 pages while the
PDF holds 24 images: rather than guess whether pages are missing, this reports
what the file actually contains -- the printed page numbers in the running
headers, the printed page totals, the brought-forward figures -- and lets the
evidence settle it.

It doubles as the first diagnostic to reach for whenever a new bank is
onboarded, or a statement refuses to reconcile.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from ..balance.chain import ChainReport
from ..money import ZERO, format_drcr, format_indian, q2
from ..parse.frame import ParseResult


@dataclass(slots=True)
class AuditReport:
    pdf: Path
    profile_name: str
    pdf_pages: int
    printed_pages: list[int] = field(default_factory=list)
    rows: int = 0
    unparsed_lines: int = 0
    mean_confidence: float = 0.0
    page_total_credit: Decimal = ZERO
    page_total_debit: Decimal = ZERO
    page_total_count: int = 0
    bf_balances: list[Decimal] = field(default_factory=list)
    first_date: str = ""
    last_date: str = ""
    chain: ChainReport | None = None
    expected: dict[str, Decimal] = field(default_factory=dict)

    @property
    def printed_page_span(self) -> str:
        if not self.printed_pages:
            return "none legible"
        return f"{min(self.printed_pages)}-{max(self.printed_pages)}"

    def render(self) -> str:
        lines: list[str] = []
        add = lines.append

        add(f"StatementBridge audit — {self.pdf.name}")
        add("=" * 64)
        add(f"profile               {self.profile_name}")
        add("")
        add("PAGES")
        add(f"  images in PDF       {self.pdf_pages}")
        add(f"  printed page nos.   {self.printed_page_span} "
            f"({len(self.printed_pages)} legible)")
        highest = max(self.printed_pages) if self.printed_pages else 0
        if highest > self.pdf_pages:
            add(f"  -> the statement runs to {highest} printed pages across "
                f"{self.pdf_pages} scanned sheets;")
            add("     more than one printed page falls on some sheets.")
        elif highest and highest < self.pdf_pages:
            add(f"  -> {self.pdf_pages - highest} sheet(s) carry no printed page number.")
        add("")
        add("EXTRACTION")
        add(f"  transaction rows    {self.rows}")
        add(f"  unparsed lines      {self.unparsed_lines}")
        add(f"  mean OCR confidence {self.mean_confidence:.1f}%")
        add(f"  date range          {self.first_date or '?'} to {self.last_date or '?'}")
        add("")
        add("PRINTED ANCHORS")
        add(f"  page-total lines    {self.page_total_count}")
        add(f"  sum of page credits {format_indian(self.page_total_credit)}")
        add(f"  sum of page debits  {format_indian(self.page_total_debit)}")
        add(f"  B/F balances seen   {len(self.bf_balances)}")
        if self.bf_balances:
            add(f"  first B/F           {format_drcr(self.bf_balances[0])}")

        if self.chain is not None:
            add("")
            add("RECONCILIATION")
            for line in self.chain.summary().splitlines():
                add(f"  {line}")

        if self.expected and self.chain is not None:
            add("")
            add("AGAINST EXPECTED")
            for label, want in self.expected.items():
                got = {
                    "opening": self.chain.opening,
                    "closing": self.chain.closing_computed,
                    "total_credit": self.chain.total_credit,
                    "total_debit": self.chain.total_debit,
                }.get(label)
                if got is None:
                    continue
                delta = q2(got - want)
                flag = "OK " if delta == 0 else "OFF"
                add(f"  {flag} {label:13} expected {format_indian(want):>18} "
                    f"got {format_indian(got):>18}  diff {format_indian(delta)}")

        if self.chain is not None and self.chain.notes:
            add("")
            add(f"UNRESOLVED ({len(self.chain.notes)})")
            for note in self.chain.notes[:25]:
                add(f"  {note}")
            if len(self.chain.notes) > 25:
                add(f"  ... and {len(self.chain.notes) - 25} more")

        return "\n".join(lines)


def build(
    pdf: Path,
    profile_name: str,
    result: ParseResult,
    chain: ChainReport | None = None,
    expected: dict[str, Decimal] | None = None,
) -> AuditReport:
    printed: set[int] = set()
    unparsed = 0
    confidences: list[float] = []
    for diagnostic in result.diagnostics:
        printed.update(diagnostic.get("printed_pages", []))
        unparsed += diagnostic.get("unparsed_lines", 0)
        if diagnostic.get("mean_confidence"):
            confidences.append(diagnostic["mean_confidence"])

    credit = sum(
        (anchor.value for anchor in result.anchors_of("PAGE_TOTAL_CREDIT") if anchor.value),
        ZERO,
    )
    debit = sum(
        (anchor.value for anchor in result.anchors_of("PAGE_TOTAL_DEBIT") if anchor.value),
        ZERO,
    )
    page_totals = len(result.anchors_of("PAGE_TOTAL_CREDIT")) + len(
        result.anchors_of("PAGE_TOTAL_DEBIT")
    )
    bf = [anchor.value for anchor in result.anchors_of("BF_BALANCE") if anchor.value]

    dates = sorted(row.date for row in result.rows if row.date)
    return AuditReport(
        pdf=pdf,
        profile_name=profile_name,
        pdf_pages=result.page_count,
        printed_pages=sorted(printed),
        rows=len(result.rows),
        unparsed_lines=unparsed,
        mean_confidence=(sum(confidences) / len(confidences)) if confidences else 0.0,
        page_total_credit=q2(credit),
        page_total_debit=q2(debit),
        page_total_count=page_totals,
        bf_balances=bf,
        first_date=dates[0].isoformat() if dates else "",
        last_date=dates[-1].isoformat() if dates else "",
        chain=chain,
        expected=expected or {},
    )
