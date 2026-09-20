"""Bounded, independently failing Ideal Text enrichment sections."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Callable, Mapping


#  HOW LONG A SECTION GETS, AND WHY THESE TWO NUMBERS DIFFER SO MUCH
#
#  FOUNDER, 2026-09-20: "no bookmarks" — on a document whose Manager work had
#  provably succeeded. The deck was drawing its reserved slots (the grey
#  circles it shows while feedback is still coming) on every paragraph, which
#  the frontend only does while the server is STILL answering `retryable`. It
#  answered that eight times across ninety seconds.
#
#  The focused retry had EIGHT seconds to do work that measurably takes twenty
#  to forty: when this same block was briefly computed inside `publish_for_arc`
#  (#580, reverted), production publication went from about a second to 22 and
#  42. That is the Manager over a six-paragraph document.
#
#  A reader given eight seconds to do forty seconds of work is detached every
#  single time — and `run_sections` cannot kill a running thread, so the work
#  then FINISHES and claims its feedback set with nobody listening. That is why
#  a claimed set existed at 15:54:36 for a take that showed nothing, and why a
#  three-paragraph document worked this morning while a six-paragraph one did
#  not. Nothing regressed; the document got longer.
#
#  THE COLD OPEN STAYS TIGHT. It is the first paint and it must not wait: a
#  section that cannot answer in two seconds reports `retryable` and the words
#  go on screen without it. Only the retry — which the client makes precisely
#  because the server asked to be asked again — gets room to finish.
#
#  Sixty would suit the Manager and not the proxy in front of us, so the retry
#  budget is deliberately short of that: past a normal request ceiling we would
#  be trading one silent failure for another. The real fix is to compute this
#  at the end of the pipeline, where no request is waiting on it (task #43).
COLD_OPEN_BUDGET_SECONDS = 2.0
FOCUSED_RETRY_BUDGET_SECONDS = 30.0


@dataclass(frozen=True)
class EnrichmentSection:
    status: str
    data: Any = None
    retryable: bool = False

    def wire(self) -> dict[str, Any]:
        result: dict[str, Any] = {"status": self.status}
        if self.data is not None:
            result["data"] = self.data
        if self.retryable:
            result["retryable"] = True
        return result


def run_sections(
    readers: Mapping[str, Callable[[], Any]], *, timeout_seconds: float = 2.0,
) -> tuple[dict[str, dict[str, Any]], dict[str, float]]:
    """Run typed readers concurrently; one timeout/failure owns one section."""
    if not readers:
        return {}, {}
    started = perf_counter()
    sections: dict[str, dict[str, Any]] = {}
    timings: dict[str, float] = {}
    pool = ThreadPoolExecutor(max_workers=min(8, len(readers)),
                              thread_name_prefix="ideal-enrichment")
    try:
        futures = {name: pool.submit(reader) for name, reader in readers.items()}
        for name, future in futures.items():
            section_started = perf_counter()
            remaining = max(0.001, timeout_seconds - (perf_counter() - started))
            try:
                data = future.result(timeout=remaining)
                sections[name] = EnrichmentSection("ready", data).wire()
            except TimeoutError:
                future.cancel()
                sections[name] = EnrichmentSection(
                    "pending", retryable=True).wire()
            except Exception:
                sections[name] = EnrichmentSection(
                    "failed", retryable=True).wire()
            timings[name] = (perf_counter() - section_started) * 1000
    finally:
        # A timed-out optional reader must not keep the HTTP response open.
        # Running calls cannot be killed by Python, but they are detached from
        # this response and their result is discarded.
        pool.shutdown(wait=False, cancel_futures=True)
    return sections, timings

