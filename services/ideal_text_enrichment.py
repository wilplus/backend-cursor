"""Bounded, independently failing Ideal Text enrichment sections."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Callable, Mapping


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

