"""CONFIG-FIRST: verify each service from its boot log, not from the Railway panel.

Ledger row A165: REASONABLE_CONFIDENCE_ENABLED must read the same on web,
worker and every cron service. The panel shows what somebody typed; the boot
log shows what that process read. Copy the boot log of each Python service
from Railway and pass it as SERVICE=PATH (PATH `-` reads that one service
from stdin).

A curl-only cron runs no Python and prints no gate line, so it is not passed.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

WATCHED: tuple[str, ...] = (
    "REASONABLE_CONFIDENCE_ENABLED",
    "TAKE_FEEDBACK_POLICY_V3_MODE",
    "MLC3_SERVICE_ENABLED",
    "MIGRATE_ON_BOOT",
    "JUDGEMENT_AFTER_FEEDBACK_ENABLED",
    "PRAISE_AFTER_PRACTICE_ENABLED",
    "MACHINE_PRACTICE_CHECK_ENABLED",
    "COMMUNITIES_ENABLED",
)

#: Printed, never compared: only bin/railway-web.sh reads it. A worker
#: legitimately has it unset.
REPORT_ONLY: tuple[str, ...] = ("MIGRATE_ON_BOOT",)

_MISSING = "(missing)"
_MARKER = "gate flags "
_TOKEN = re.compile(r"^([A-Z][A-Z0-9_]*)=(\S+)$")
_DESCRIPTION = __doc__.splitlines()[0]


def parse_gate_line(text: str) -> dict[str, str] | None:
    """The newest `gate flags ` line, as {NAME: value}. None if there is none.

    A log can hold several boots; the last line wins. Tokens that are not
    NAME=value are ignored, so a Railway prefix on the line does not matter.
    """
    chosen: str | None = None
    for line in text.splitlines():
        if _MARKER in line:
            chosen = line
    if chosen is None:
        return None
    rest = chosen[chosen.find(_MARKER) + len(_MARKER) :]
    parsed: dict[str, str] = {}
    for token in rest.split():
        match = _TOKEN.match(token)
        if match is not None:
            parsed[match.group(1)] = match.group(2)
    return parsed


def _compared_names(services: dict[str, dict[str, str] | None]) -> list[str]:
    """Watched names, then any other name a gate line actually carried."""
    skip = set(REPORT_ONLY)
    names: list[str] = []
    seen: set[str] = set()
    for name in WATCHED:
        if name not in skip and name not in seen:
            seen.add(name)
            names.append(name)
    for flags in services.values():
        if flags is None:
            continue
        for name in flags:
            if name not in skip and name not in seen:
                seen.add(name)
                names.append(name)
    return names


def _value(flags: dict[str, str] | None, name: str) -> str:
    if flags is None or name not in flags:
        return _MISSING
    return flags[name]


def _problems(services: dict[str, dict[str, str] | None]) -> list[str]:
    """Mismatches across services that printed a gate line, plus missing lines."""
    problems = [
        f"NO GATE LINE: {name}"
        for name, flags in services.items()
        if flags is None
    ]
    present = {
        name: flags for name, flags in services.items() if flags is not None
    }
    for switch in _compared_names(services):
        values = [_value(flags, switch) for flags in present.values()]
        if len(set(values)) <= 1:
            continue
        detail = " ".join(
            f"{name}={_value(flags, switch)}" for name, flags in present.items()
        )
        problems.append(f"MISMATCH {switch}: {detail}")
    return problems


def _render(
    services: dict[str, dict[str, str] | None],
    problems: list[str],
) -> list[str]:
    names = list(services)
    rows = [["switch", *names]]
    notes: list[str] = [""]
    for switch in WATCHED:
        rows.append([switch, *[_value(services[name], switch) for name in names]])
        if switch in REPORT_ONLY:
            notes.append("  (web only, not compared)")
        else:
            notes.append("")
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    lines = [
        "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)) + note
        for row, note in zip(rows, notes, strict=True)
    ]
    lines.append("")
    if problems:
        lines.extend(problems)
        lines.append(f"boot_switch_report: {len(problems)} problem(s)")
    else:
        agreed = len(_compared_names(services))
        lines.append(
            "boot_switch_report: ok "
            f"({len(services)} services agree on {agreed} switches)"
        )
    return lines


def compare(
    services: dict[str, dict[str, str] | None],
) -> tuple[list[str], list[str]]:
    """Report lines and problems. A service with no gate line is not compared."""
    problems = _problems(services)
    return _render(services, problems), problems


def _assignments(items: list[str]) -> dict[str, str]:
    if len(items) < 2:
        raise ValueError(
            "boot_switch_report: need at least two services (SERVICE=PATH)"
        )
    assignments: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(
                f"boot_switch_report: malformed argument {item!r}: "
                "expected SERVICE=PATH"
            )
        name, path = item.split("=", 1)
        if not name:
            raise ValueError(
                f"boot_switch_report: malformed argument {item!r}: empty name"
            )
        if name in assignments:
            raise ValueError(f"boot_switch_report: duplicate service {name}")
        assignments[name] = path
    if sum(path == "-" for path in assignments.values()) > 1:
        raise ValueError(
            "boot_switch_report: at most one service may read stdin"
        )
    return assignments


def _read(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """0 when services agree, 1 on a mismatch or missing line, 2 on bad input."""
    parser = argparse.ArgumentParser(description=_DESCRIPTION)
    parser.add_argument(
        "assignments",
        nargs="*",
        metavar="SERVICE=PATH",
        help="service name and boot log; PATH - reads stdin",
    )
    args = parser.parse_args(argv)
    try:
        assignments = _assignments(args.assignments)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    loaded: dict[str, dict[str, str] | None] = {}
    for name, path in assignments.items():
        try:
            text = _read(path)
        except OSError as exc:
            print(
                f"boot_switch_report: cannot read {name}={path}: {exc}",
                file=sys.stderr,
            )
            return 2
        loaded[name] = parse_gate_line(text)
    report_lines, problems = compare(loaded)
    sys.stdout.write("\n".join(report_lines) + "\n")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
