"""The category summary, and the check that makes it worth printing.

This is the sheet the firm already reads: one line per category, a count, a
credit total and a debit total, every category listed whether or not it occurred.
The zero rows are not padding -- they are the checklist that shows a category was
considered and found absent, rather than quietly never looked for.

What makes it more than a presentation layer is that **it must agree with the
balance chain**. Every settled row belongs to exactly one category, so the
category credits have to sum to the chain's credits and the category debits to
its debits, to the paisa. That is the same argument the balance engine runs on --
a statement over-determines itself, and the redundancy is what catches the error
-- applied one level up. If a row were dropped from the summary, or counted
twice, or its amount read from somewhere other than the settled frame, the
totals would part company and :meth:`CategorySummary.reconciles_with` would say
so.

Note what is *not* claimed. The summary tying proves the arithmetic of the
classification, not its correctness: every row landing in ``UNCLASSIFIED`` still
ties perfectly. Labels are checked by :attr:`CategorySummary.unclassified` and by
a human, never by this.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Sequence

from ..balance.chain import ChainReport
from ..money import ZERO, format_indian, q2
from .engine import Movement
from .taxonomy import SUMMARY_ORDER, Category


@dataclass(frozen=True, slots=True)
class CategoryTotal:
    """One line of the summary."""

    category: Category
    count: int = 0
    credit: Decimal = ZERO
    debit: Decimal = ZERO

    @property
    def occurred(self) -> bool:
        return self.count > 0


@dataclass(slots=True)
class CategorySummary:
    """Every category, in the workbook's order, with what landed in it."""

    totals: list[CategoryTotal] = field(default_factory=list)
    #: Rows whose classification a person should look at: unclassified, plus
    #: the matches the rules themselves flagged as worth confirming.
    review_count: int = 0
    #: Ledger names actually used, so the firm can create them in Tally once.
    ledgers: list[str] = field(default_factory=list)

    def of(self, category: Category) -> CategoryTotal:
        for total in self.totals:
            if total.category is category:
                return total
        return CategoryTotal(category=category)

    @property
    def count(self) -> int:
        return sum(total.count for total in self.totals)

    @property
    def total_credit(self) -> Decimal:
        return q2(sum((total.credit for total in self.totals), ZERO))

    @property
    def total_debit(self) -> Decimal:
        return q2(sum((total.debit for total in self.totals), ZERO))

    @property
    def unclassified(self) -> int:
        return self.of(Category.UNCLASSIFIED).count

    @property
    def contra_count(self) -> int:
        return sum(total.count for total in self.totals if total.category.contra)

    def reconciles_with(self, chain: ChainReport) -> bool:
        """Do the category totals equal the balance chain's, to the paisa?"""
        return (
            self.total_credit == chain.total_credit
            and self.total_debit == chain.total_debit
            and self.count == chain.credit_count + chain.debit_count
        )

    def variance_against(self, chain: ChainReport) -> tuple[Decimal, Decimal]:
        """Category totals minus chain totals: (credit, debit). Exact."""
        return (
            q2(self.total_credit - chain.total_credit),
            q2(self.total_debit - chain.total_debit),
        )

    def as_dict(self) -> dict[str, Any]:
        """A transportable summary. Money as strings, as everywhere else."""
        return {
            "categories": [
                {
                    "code": total.category.value,
                    "description": total.category.description,
                    "contra": total.category.contra,
                    "count": total.count,
                    "credit": str(total.credit),
                    "debit": str(total.debit),
                }
                for total in self.totals
            ],
            "count": self.count,
            "total_credit": str(self.total_credit),
            "total_debit": str(self.total_debit),
            "unclassified": self.unclassified,
            "review_count": self.review_count,
            "contra_count": self.contra_count,
            "ledgers": list(self.ledgers),
        }

    def render(self, chain: ChainReport | None = None) -> str:
        lines = [
            f"{'Cat':<9}{'Description':<30}{'Count':>7}"
            f"{'Credit':>18}{'Debit':>18}",
            "-" * 82,
        ]
        for total in self.totals:
            lines.append(
                f"{total.category.value:<9}{total.category.description:<30}"
                f"{total.count:>7}"
                f"{format_indian(total.credit, blank_zero=True):>18}"
                f"{format_indian(total.debit, blank_zero=True):>18}"
            )
        lines.append("-" * 82)
        lines.append(
            f"{'':<9}{'TOTAL':<30}{self.count:>7}"
            f"{format_indian(self.total_credit):>18}"
            f"{format_indian(self.total_debit):>18}"
        )
        if chain is not None:
            credit_variance, debit_variance = self.variance_against(chain)
            verdict = "ties" if self.reconciles_with(chain) else "DOES NOT TIE"
            lines.append("")
            lines.append(f"against the balance chain: {verdict}")
            if not self.reconciles_with(chain):
                lines.append(
                    f"  credit {format_indian(credit_variance)}   "
                    f"debit {format_indian(debit_variance)}"
                )
        lines.append("")
        lines.append(
            f"unclassified {self.unclassified}   for review {self.review_count}   "
            f"contra {self.contra_count}"
        )
        return "\n".join(lines)


def summarise(movements: Sequence[Movement]) -> CategorySummary:
    """Total a classified statement by category."""
    counts: dict[Category, int] = {}
    credits: dict[Category, Decimal] = {}
    debits: dict[Category, Decimal] = {}
    review = 0
    ledgers: list[str] = []

    for movement in movements:
        category = movement.classification.category
        counts[category] = counts.get(category, 0) + 1
        credits[category] = credits.get(category, ZERO) + movement.credit
        debits[category] = debits.get(category, ZERO) + movement.debit
        if movement.classification.needs_review:
            review += 1
        if movement.classification.ledger not in ledgers:
            ledgers.append(movement.classification.ledger)

    return CategorySummary(
        totals=[
            CategoryTotal(
                category=category,
                count=counts.get(category, 0),
                credit=q2(credits.get(category, ZERO)),
                debit=q2(debits.get(category, ZERO)),
            )
            # Every category, present or not: the zero lines are the checklist.
            for category in SUMMARY_ORDER
        ],
        review_count=review,
        ledgers=ledgers,
    )
