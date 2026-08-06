"""What a rule is, and what it is allowed to decide.

A rule is data. That is the same choice :mod:`statementbridge.parse.profiles.base`
makes for bank layouts, and for the same reason: the firm will accumulate far
more narration vocabulary than bank formats, and each addition should be a row
in a pack rather than a branch in a classifier. It is also what makes step 7's
user-created rules a storage problem rather than a redesign -- a rule is already
a name, a category, some words and a direction, all of which survive a round
trip through a database.

Matching is layered exactly as :func:`statementbridge.parse.rowkind.classify_line`
layers it, because the input has the same damage:

1. every one of the rule's words present in the narration's canonical words;
2. failing that, and only for words long enough to make it safe, a fuzzy
   comparison against each narration word.

The length guard is not caution for its own sake. ``fuzz.partial_ratio`` of a
three-letter token against a long narration is close to a coin toss -- ``upi``
would find itself inside half the statement -- so short words must match exactly.
They can afford to: the canonical alphabet already absorbs the substitutions
that actually happen at 150 DPI, so ``G5T`` and ``GST`` are the same string
before any fuzzy comparison is reached.

**A rule may not contradict its category.** ``Rule`` refuses at construction to
give a debit-only category to a credit-only rule, and ``Pack`` refuses to hold
two rules with the same id. Both faults are silent in output -- a credit posted
to an expense ledger looks like a number, not like an error -- and both are
detectable the moment the pack is built, so that is where they are caught.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Final, Iterable, Sequence

from rapidfuzz import fuzz

from .normalise import Narration, canon_word, name_words
from .taxonomy import Category, Direction

#: Shortest rule word that may be matched fuzzily. Below it, exact only.
_FUZZY_MINIMUM: Final[int] = 5
#: Whole-word similarity, not partial: the words being compared are already
#: isolated, so a partial ratio would only re-admit the substring problem.
_FUZZY_THRESHOLD: Final[int] = 85


@dataclass(frozen=True, slots=True)
class Context:
    """What a rule needs to know about the account, beyond the narration."""

    #: Canonical words of the confirmed account holder's name, honorifics gone.
    holder_words: tuple[str, ...] = ()

    @classmethod
    def for_holder(cls, holder: str | None) -> "Context":
        return cls(holder_words=name_words(holder))


Predicate = Callable[[Narration, Context], bool]

_PREDICATES: dict[str, Predicate] = {}


def structural(name: str) -> Callable[[Predicate], Predicate]:
    """Register a named structural test a rule can refer to.

    Some narrations are recognisable by shape rather than vocabulary -- a bare
    cheque number and a branch name carries no word worth matching. Naming the
    test keeps the rule itself declarative, and keeps it serialisable for the
    day rules come out of a database.
    """

    def register(function: Predicate) -> Predicate:
        _PREDICATES[name] = function
        return function

    return register


def get_predicate(name: str) -> Predicate:
    if name not in _PREDICATES:
        raise KeyError(f"unknown structural predicate {name!r}; known: {sorted(_PREDICATES)}")
    return _PREDICATES[name]


@structural("holder_name")
def _holder_name(narration: Narration, context: Context) -> bool:
    """The account holder's own name appears in the narration.

    Every name word must be present, not merely one: a statement full of
    ``NAG`` surnames would otherwise tag a third party as a self-transfer, and
    a self-transfer is a contra voucher -- it leaves the profit and loss account
    entirely. The workbook's Notes make the same call and flag the residual
    risk, which is why rules using this predicate set ``review``.
    """
    if not context.holder_words:
        return False
    return all(word in narration.words for word in context.holder_words)


@structural("bare_cheque_number")
def _bare_cheque_number(narration: Narration, context: Context) -> bool:
    """A cheque or instrument number and a place, with no transaction verb.

    ``184693 DHARMANAGAR`` is a branch deposit, but nothing in it says deposit.
    What identifies it is the shape: an instrument number, and at most a word or
    two of branch name with none of the rail vocabulary (UPI, NEFT, IMPS, cash)
    that every other kind of credit carries.

    The length window is where "is this a cheque number?" is actually decided.
    Indian cheque and instrument numbers run to six digits; a twelve-digit run
    is a UTR or an account number, and a narration built around one belongs to
    the rail that issued it.
    """
    if len(narration.words) > 2:
        return False
    if any(word in _RAIL_WORDS for word in narration.words):
        return False
    return any(_CHEQUE_DIGITS[0] <= len(number) <= _CHEQUE_DIGITS[1]
               for number in narration.numbers)


#: Digit count that reads as an instrument number rather than a UTR.
_CHEQUE_DIGITS: Final[tuple[int, int]] = (4, 8)

#: Vocabulary that means some other rule should have claimed the row.
_RAIL_WORDS: Final[frozenset[str]] = frozenset(
    canon_word(word)
    for word in ("upi", "neft", "imps", "rtgs", "cash", "atm", "chq", "cheque", "int")
)


@dataclass(frozen=True, slots=True)
class Rule:
    """One classification decision, expressed as data."""

    id: str
    category: Category
    #: Words that must all appear. Given as written; canonicalised on build.
    words: tuple[str, ...] = ()
    #: The direction this rule claims. Must not contradict the category.
    direction: Direction = Direction.EITHER
    #: Overrides the category's default ledger. Used where a payer is known
    #: precisely enough to deserve its own ledger.
    ledger: str | None = None
    #: Mark matched rows for human attention without withholding the answer.
    review: bool = False
    #: Name of a registered structural test that must also pass.
    predicate: str | None = None
    why: str = ""

    def __post_init__(self) -> None:
        if not self.words and not self.predicate:
            raise ValueError(f"rule {self.id!r} matches nothing: no words, no predicate")
        if not self.category.direction.admits(self.direction):
            raise ValueError(
                f"rule {self.id!r} is {self.direction.value} but category "
                f"{self.category.value} is {self.category.direction.value}-only"
            )
        if self.predicate is not None:
            get_predicate(self.predicate)  # fail at build time, not at match time
        object.__setattr__(
            self, "words", tuple(canon_word(word) for word in self.words if canon_word(word))
        )

    def ledger_for(self, holder: str | None) -> str:
        return self.ledger or self.category.ledger(holder)

    def matches(
        self, narration: Narration, direction: Direction, context: Context
    ) -> bool:
        if not self.direction.admits(direction):
            return False
        if self.predicate is not None and not get_predicate(self.predicate)(
            narration, context
        ):
            return False
        return all(self._word_present(word, narration) for word in self.words)

    def _word_present(self, word: str, narration: Narration) -> bool:
        if narration.has(word):
            return True
        if len(word) < _FUZZY_MINIMUM:
            return False
        return any(
            fuzz.ratio(word, candidate) >= _FUZZY_THRESHOLD
            for candidate in narration.words
        )


@dataclass(frozen=True, slots=True)
class Pack:
    """An ordered set of rules. First match wins, so order is the priority.

    Specific rules come before the generic ones they would otherwise be
    swallowed by -- the same convention, for the same reason, as the pattern
    table in :mod:`statementbridge.parse.rowkind`.
    """

    name: str
    rules: tuple[Rule, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for rule in self.rules:
            if rule.id in seen:
                raise ValueError(f"duplicate rule id {rule.id!r} in pack {self.name!r}")
            seen.add(rule.id)

    def __iter__(self) -> Iterable[Rule]:
        return iter(self.rules)

    def __len__(self) -> int:
        return len(self.rules)

    def first_match(
        self, narration: Narration, direction: Direction, context: Context
    ) -> Rule | None:
        for rule in self.rules:
            if rule.matches(narration, direction, context):
                return rule
        return None

    def get(self, rule_id: str) -> Rule:
        for rule in self.rules:
            if rule.id == rule_id:
                return rule
        raise KeyError(f"no rule {rule_id!r} in pack {self.name!r}")


def build(name: str, rules: Sequence[Rule]) -> Pack:
    return Pack(name=name, rules=tuple(rules))
