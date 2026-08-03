"""Offline ASR evaluation harness (F1 — piece (a), perfect per-slide transcript).

WHY THIS IS A PACKAGE AND NOT A SERVICE
---------------------------------------
Nothing here is imported by the live loop. `services/` is the live import
surface; this package is bench equipment. It reads audio + reference
transcripts off disk, calls ASR providers, and prints numbers. It never
touches the DB, never writes a transcript, and is never reachable from a
route. That separation is deliberate: an eval harness that can affect the
running record→transcribe→coach→read loop is a liability, not a gate.

WHAT IT MEASURES, AND WHY THOSE THINGS
--------------------------------------
The north star is not "a good transcript" — it is "every word bucketed to
the slide that was on screen when it was spoken". That makes the ranking of
metrics unusual, and getting the ranking wrong is how an ASR migration ships
a regression while the headline number improves:

  1. slide-bucket agreement  — THE metric. Same tap timeline, two word
                               streams: what fraction of words land on the
                               same slide? A model can win on WER and lose
                               here, and losing here is losing F1.
  2. boundary-critical error — WER and timestamp error restricted to words
                               near a slide tap. An error mid-slide costs a
                               word; an error at a boundary costs a slide
                               misattribution.
  3. timestamp error         — |Δstart| against reference word times.
  4. verbatim WER            — fillers KEPT. willab primes Whisper with a
                               disfluent prompt on purpose; a model that
                               silently cleans "um" scores better on
                               conventional WER and is a regression here.
  5. content WER             — fillers stripped. The number that compares to
                               published benchmarks. Reported last on
                               purpose — it is the least decision-relevant.

AC-9: internal engineering read. Nothing computed here is ever surfaced to
a user, and no module in this package is importable from a user payload
path.
"""
from __future__ import annotations

__all__ = ["normalize", "metrics", "corpus", "providers", "report"]
