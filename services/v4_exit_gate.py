"""The V4 exit gate (V4 Phase 1, BEXIT; build plan D-ML-16; founder V21 A,
V15a A, V22a B, V22c B, O5, O4, QG4 B, QG7 A).

V4 may be switched on only when every line below passes. The founder reads
this report; nothing here flips anything (the switch is a reviewed change
after the founder's word, CONFIG-FIRST).

  1. Golden-set agreement (V21 A, QG4 B): on at least ``MIN_GOLDEN`` blocks
     the founder answered on "Pick the moment for feedback", V4's moment
     matches the founder's more often than V3's, by any margin.
  2. Next-Take rise (V21 A, P5): of the paragraphs each picked for work, the
     share that clearly rose by the next Take (B1.5), V4 above V3, on at
     least ``MIN_RISES`` measured picks each. Before the switch V3 served
     every Take, so V4's line is "what happened to the paragraphs V4 would
     have picked"; after it, the few speakers who see V4 answer it (V22a B,
     QG7 A). The report says which.
  3. Coverage holds (contract 24c/24d): at least ``COVERAGE_SHARE`` of the
     Takes served since the dark run began met their slide floor (D-ML-5).
     V4 keeps Confident Voice on every block (P3), so it cannot lower this.
  4. Practise read (O5): p90 at most 5 s from Stop, on the phone's clock where
     it reported (B1.4).
  5. Reached bar calibrated (O4): enough blind coach answers for a bar that
     is not the placeholder (B1.4b).
  6. Standing on its own (V15a A): V4 fell back to V3 on at most one block
     in five.

Every value here is internal (AC-9): this is a founder-only report, never a
payload. The minimums are starting values the founder can change.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

#: V21 A: "at least a minimum number of golden blocks (I suggest 100)".
MIN_GOLDEN = 100
MIN_RISES = 100
COVERAGE_SHARE = 0.95
MAX_FALLBACK_SHARE = 0.2
IMPROVE_KINDS = ("rewrite", "exercise")


def _line(name: str, passed: bool, **facts: Any) -> dict:
    return {"line": name, "passed": bool(passed), **facts}


def rise_lines(outcomes: Iterable[dict], picks: Iterable[dict]) -> tuple[dict, dict]:
    """(V4, V3) rise shares over measured improvement picks. Pure.

    ``outcomes``: v4_pick_outcomes rows; ``picks``: v4_picks rows (V4's own
    pick on the same block of the same Take)."""
    picked = {(str(p.get("take_session_id")), str(p.get("block_id")))
              for p in picks if p.get("picked")}
    v4: dict[str, Any] = {"measured": 0, "rose": 0}
    v3: dict[str, Any] = {"measured": 0, "rose": 0}
    for row in outcomes:
        if row.get("outcome") not in ("rose", "did_not_rise"):
            continue
        rose = row["outcome"] == "rose"
        key = (str(row.get("take_session_id")), str(row.get("block_id")))
        if key in picked:
            v4["measured"] += 1
            v4["rose"] += int(rose)
        if set(row.get("v3_picks") or []) & set(IMPROVE_KINDS):
            v3["measured"] += 1
            v3["rose"] += int(rose)
    for side in (v4, v3):
        side["share"] = side["rose"] / side["measured"] if side["measured"] else None
    return v4, v3


def evaluate(*, golden: dict, rises: tuple[dict, dict], coverage: Iterable[dict],
             practise: dict, bar: dict, pick_takes: Iterable[dict],
             served_by: str = "v3") -> dict:
    """The six lines and the verdict. Pure."""
    lines = []
    g_v4, g_v3, n = golden.get("v4_agreement"), golden.get("v3_agreement"), golden.get("golden_blocks", 0)
    lines.append(_line("golden_agreement",
                       n >= MIN_GOLDEN and g_v4 is not None and g_v3 is not None and g_v4 > g_v3,
                       golden_blocks=n, minimum=MIN_GOLDEN, v4=g_v4, v3=g_v3))
    v4, v3 = rises
    lines.append(_line("next_take_rise",
                       v4["measured"] >= MIN_RISES and v3["measured"] >= MIN_RISES
                       and v4["share"] is not None and v3["share"] is not None
                       and v4["share"] > v3["share"],
                       v4=v4, v3=v3, minimum=MIN_RISES,
                       measured_on=("paragraphs V4 would have picked; V3 served them"
                                    if served_by == "v3" else "speakers who see V4")))
    rows = list(coverage)
    met = sum(1 for r in rows if r.get("floor_met"))
    share = met / len(rows) if rows else None
    lines.append(_line("coverage_holds", share is not None and share >= COVERAGE_SHARE,
                       takes=len(rows), floor_met=met, share=share, minimum_share=COVERAGE_SHARE))
    lines.append(_line("practise_read_p90", bool(practise.get("meets_o5")),
                       p90_ms=practise.get("p90_ms"), tries=practise.get("tries"),
                       clocks=practise.get("clocks")))
    lines.append(_line("reached_bar_calibrated", bar.get("status") == "calibrated",
                       bar=bar.get("bar"), answers=bar.get("answers"), status=bar.get("status")))
    takes = list(pick_takes)
    blocks = sum(int(t.get("blocks") or 0) for t in takes)
    fallback = sum(int(t.get("fallback_blocks") or 0) for t in takes)
    fshare = fallback / blocks if blocks else None
    lines.append(_line("stands_on_its_own", fshare is not None and fshare <= MAX_FALLBACK_SHARE,
                       blocks=blocks, fallback_blocks=fallback, share=fshare,
                       maximum_share=MAX_FALLBACK_SHARE))
    return {"passed": all(line["passed"] for line in lines), "lines": lines}


def _all(client: Any, table: str, columns: str, limit: int = 50000) -> list[dict]:
    return list(client.table(table).select(columns).limit(limit).execute().data or [])


def gather(database: Any, *, served_by: str = "v3") -> dict:
    """Read everything the gate needs and evaluate it. Read-only."""
    from services import v4_coach_sheets, v4_practice_read, v4_reached_bar
    client = database.client
    sheets = _all(client, "v4_moment_pick_sheets", "*")
    outcomes = _all(client, "v4_pick_outcomes", "take_session_id,block_id,outcome,v3_picks")
    picks = _all(client, "v4_picks", "take_session_id,block_id,picked")
    pick_takes = _all(client, "v4_pick_takes", "take_session_id,blocks,fallback_blocks")
    coverage = database.list_take_feedback_coverage()
    reads = _all(client, "v4_practice_reads",
                 "outcome,willfident,server_received_at,server_read_at,phone_wait_ms")
    return evaluate(
        golden=v4_coach_sheets.golden_agreement(sheets),
        rises=rise_lines(outcomes, picks),
        coverage=coverage,
        practise=v4_practice_read.p90_report(reads),
        bar=v4_reached_bar.gather(database),
        pick_takes=pick_takes,
        served_by=served_by,
    )


def plain_words(report: dict) -> list[str]:
    """One plain line per gate line, for the founder's panel. Pure."""
    names = {
        "golden_agreement": "Your golden-set blocks: V4 agrees with you more often than V3",
        "next_take_rise": "Paragraphs picked for work rise more often by the next Take with V4",
        "coverage_holds": "Every slide still gets its feedback",
        "practise_read_p90": "The practise read arrives within 5 seconds for 9 tries in 10",
        "reached_bar_calibrated": "The 'reached' bar is set from coach answers",
        "stands_on_its_own": "V4 decides on its own in at least 4 blocks of 5",
    }
    return [f"{'PASS' if line['passed'] else 'NOT YET'}: {names[line['line']]}"
            for line in report.get("lines") or []]


def missing(report: dict) -> Optional[list[str]]:
    """The lines still short, by name, or None when the gate passes."""
    short = [line["line"] for line in report.get("lines") or [] if not line["passed"]]
    return short or None
