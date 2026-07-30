"""Command line entry point for Phase 1 (no GUI yet)."""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path

from .audit import report as audit_report
from .balance.repair import settle
from .money import parse_amount, signed_from_drcr
from .parse import scanned
from .parse.profiles import gramin_cc, sbi_current  # noqa: F401  (registers profiles)
from .parse.profiles.base import all_profiles, get_profile

#: Figures the client supplied for the two fixtures, used by `audit --expect`.
EXPECTED = {
    "gramin_cc": {
        "opening": Decimal("-7185895.72"),
        "total_credit": Decimal("40640716.00"),
        "total_debit": Decimal("42553191.50"),
        "closing": Decimal("-9098371.22"),
    },
    "sbi_current": {
        "opening": Decimal("0.00"),
        "total_credit": Decimal("214589593.12"),
        "total_debit": Decimal("214391776.02"),
        "closing": Decimal("197817.10"),
    },
}


def _progress(position: int, total: int) -> None:
    print(f"\r  page {position}/{total}", end="", file=sys.stderr, flush=True)


def _run(args: argparse.Namespace):
    profile = get_profile(args.profile)
    result = scanned.parse_pdf(
        Path(args.pdf),
        profile,
        dpi=args.dpi,
        first=args.first,
        last=args.last,
        progress=None if args.quiet else _progress,
    )
    if not args.quiet:
        print(file=sys.stderr)

    opening = _opening_balance(args, profile, result)
    closing = parse_amount(args.closing).value if args.closing else None
    if closing is not None and profile.is_overdraft:
        closing = signed_from_drcr(closing, "DR")
    chain, _ = settle(result.rows, opening, closing=closing)
    return profile, result, chain


def _opening_balance(args, profile, result) -> Decimal:
    if args.opening:
        value = parse_amount(args.opening).value or Decimal("0.00")
        return signed_from_drcr(value, "DR" if profile.is_overdraft else "CR")
    # Fall back to the first brought-forward figure the scan found.
    for anchor in result.anchors:
        if anchor.kind in ("BF_BALANCE", "OPENING_BALANCE") and anchor.value is not None:
            marker = anchor.marker or ("DR" if profile.is_overdraft else "CR")
            return signed_from_drcr(anchor.value, marker)
    return Decimal("0.00")


def cmd_audit(args: argparse.Namespace) -> int:
    profile, result, chain = _run(args)
    expected = EXPECTED.get(profile.key, {}) if args.expect else {}
    report = audit_report.build(
        Path(args.pdf), profile.name, result, chain, expected
    )
    print(report.render())
    return 0


def cmd_parse(args: argparse.Namespace) -> int:
    _, result, chain = _run(args)
    frame = result.to_dataframe()
    if args.out:
        frame.to_csv(args.out, index=False)
        print(f"wrote {len(frame)} rows to {args.out}", file=sys.stderr)
    else:
        print(frame.to_string(max_rows=40))
    print(file=sys.stderr)
    print(chain.summary(), file=sys.stderr)
    return 0 if chain.reconciled else 1


def cmd_profiles(_: argparse.Namespace) -> int:
    for profile in all_profiles():
        kind = "cash-credit/OD" if profile.is_overdraft else "regular"
        print(f"{profile.key:14} {kind:15} {profile.name}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="statementbridge",
        description="Convert Indian bank statement PDFs for Tally. Offline.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(sub):
        sub.add_argument("pdf")
        sub.add_argument("--profile", required=True, help="bank layout profile key")
        sub.add_argument("--dpi", type=int, default=300)
        sub.add_argument("--first", type=int, default=None, help="first PDF page")
        sub.add_argument("--last", type=int, default=None, help="last PDF page")
        sub.add_argument("--opening", default=None, help="opening balance, e.g. '71,85,895.72'")
        sub.add_argument("--closing", default=None, help="printed closing balance")
        sub.add_argument("--quiet", action="store_true")

    audit_cmd = subparsers.add_parser(
        "audit", help="report what a PDF actually contains, without assumptions"
    )
    add_common(audit_cmd)
    audit_cmd.add_argument(
        "--expect", action="store_true", help="compare against the known fixture figures"
    )
    audit_cmd.set_defaults(func=cmd_audit)

    parse_cmd = subparsers.add_parser("parse", help="extract the transaction frame")
    add_common(parse_cmd)
    parse_cmd.add_argument("--out", default=None, help="write CSV here")
    parse_cmd.set_defaults(func=cmd_parse)

    profiles_cmd = subparsers.add_parser("profiles", help="list known bank profiles")
    profiles_cmd.set_defaults(func=cmd_profiles)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
