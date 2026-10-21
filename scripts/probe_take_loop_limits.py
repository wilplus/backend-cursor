"""Probe the offline half of the Take loop against distinct use cases.

The evidence behind docs/audit/LIMITATIONS-ASSESSMENT-2026-10-19.md. It
runs the real production functions, with no database, no network and no
provider, on synthetic Whisper-shaped input:

    words → restore_punctuation → split_runon_sentences
          → build_canonical_pieces (slide split)
          → the Ideal Text builder (_spoken_rows → _lay_out → _finish_document)
          → merge_by_slide / follow_the_take (Take 2)
          → phrase_in_version (helper words)

plus the speech gate on synthetic audio and the Whisper request builder.

It is a probe, not a test: it prints what happened for each scenario and
never fails. Transcription quality, the LLM layers and the feedback
Manager need a provider and the database, so they are out of its reach.

    .venv-ci/bin/python scripts/probe_take_loop_limits.py
"""
from __future__ import annotations

import os
import sys
from typing import Any, Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
# Always CI's placeholders, never whatever the shell holds: importing a
# service builds a database client, and a probe must not be able to reach
# a real database. The key is the public Supabase demo JWT CI uses.
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["SUPABASE_URL"] = "https://ci-placeholder.invalid"
os.environ["SUPABASE_KEY"] = "ci-placeholder-key"
os.environ["JWT_SECRET"] = "ci-placeholder-secret"
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9s"
    "ZSI6InNlcnZpY2Vfcm9sZSIsImV4cCI6MTk4MzgxMjk5Nn0.EGIM96RAZx35lJzdJsyH-qQwv8Hdp7fsn3W0YpN81IU")
os.environ.pop("OPENAI_API_KEY", None)

import numpy as np  # noqa: E402

from services.min_content_gate import evaluate_min_content  # noqa: E402
from services.openai_service import _whisper_request  # noqa: E402
from services.recording_piece_analysis import build_canonical_pieces  # noqa: E402
from services.slide_helper_words import phrase_in_version, within_cap  # noqa: E402
from services.slide_word_split import (  # noqa: E402
    build_slide_transcripts,
    context_with_clock_offset,
    restore_punctuation,
    split_runon_sentences,
)
from services.take_rebuild import follow_the_take, merge_by_slide  # noqa: E402
from services.transcript_document import (  # noqa: E402
    _finish_document,
    _lay_out,
    _spoken_rows,
)

WORD_S = 0.32   # one spoken word, seconds
GAP_S = 0.08    # between words in a phrase


def words_from(phrases: list[tuple[str, float]], start: float = 0.0) -> tuple[list, list]:
    """Whisper-shaped (words, segments) from [(text, pause_after_s)]."""
    words: list = []
    segments: list = []
    t = start
    for text, pause in phrases:
        seg_start = t
        for token in text.split():
            words.append({"word": token.strip(".,!?;:"), "start": round(t, 3),
                          "end": round(t + WORD_S, 3)})
            t += WORD_S + GAP_S
        segments.append({"text": text, "start": seg_start, "end": t})
        t += pause
    return words, segments


def ideal_text(words: list, segments: list, context: Optional[dict],
               *, language: Optional[str] = None, sid: str = "take-1",
               take_index: int = 1) -> tuple[Optional[dict], list]:
    """The production path from Whisper words to the Take's Ideal Text."""
    context = context_with_clock_offset(context or {})
    words = split_runon_sentences(restore_punctuation(words, segments))
    pieces = build_canonical_pieces(words, context)
    snips = []
    for i, p in enumerate(pieces):
        provenance: dict = {"index": p.get("index")}
        if p.get("slide_index") is not None:
            provenance["slide_index"] = p["slide_index"]
        snips.append({"id": f"{sid}-s{i}", "transcript": p["transcript"],
                      "start_offset_ms": p["start_offset_ms"],
                      "duration_ms": p["duration_ms"], "language": language,
                      "metrics": {"piece": provenance}})
    rows = _spoken_rows(snips, {}, {}, {})
    finished = _finish_document(*_lay_out(rows, sid, take_index))
    if finished is None:
        return None, pieces
    text, doc_pieces, paragraphs = finished
    return {"text": text, "pieces": doc_pieces, "paragraphs": paragraphs,
            "take_session_id": sid, "take_index": take_index}, pieces


def show(doc: Optional[dict], width: int = 110) -> str:
    if not doc:
        return "    (no Ideal Text)"
    out = []
    blocks = doc["text"].split("\n\n")
    for para, block in zip(doc["paragraphs"], blocks):
        shown = block if len(block) <= width else block[:width] + "…"
        out.append(f"    [slide {para['slide_index']}] {shown}")
    return "\n".join(out)


def deck(n: int) -> list:
    return [{"title": f"Slide {i + 1}", "body": ""} for i in range(n)]


def heading(code: str, title: str) -> None:
    print(f"\n=== {code} {title}")


# ── Scenarios ────────────────────────────────────────────────────────────

def s01_clean_deck() -> None:
    heading("S01", "3-slide deck, clean taps between sentences (the happy path)")
    w, s = words_from([
        ("Good morning everyone, today I want to talk about our onboarding.", 1.0),
        ("Last quarter we lost forty percent of new users in the first week.", 1.0),
        ("So we rebuilt the first five minutes around one single action.", 1.0),
    ])
    adv = [{"index": 0, "t_ms": 0}, {"index": 1, "t_ms": 5300}, {"index": 2, "t_ms": 11000}]
    doc, _ = ideal_text(w, s, {"slides": deck(3), "slide_advances": adv})
    print(show(doc))


def s02_tap_lag() -> None:
    heading("S02", "tap 700 ms late vs speech, with and without a measured clock offset")
    w, s = words_from([
        ("Our churn problem starts on day one.", 0.15),
        ("The fix is a guided first project.", 0.5),
    ])
    second = next(x for x in w if x["word"] == "The")["start"]
    adv = [{"index": 0, "t_ms": 0}, {"index": 1, "t_ms": int(second * 1000) + 700}]
    doc, _ = ideal_text(w, s, {"slides": deck(2), "slide_advances": adv})
    print("  no offset sent:")
    print(show(doc))
    doc, _ = ideal_text(w, s, {"slides": deck(2), "slide_advances": adv,
                               "slide_clock_offset_ms": 700})
    print("  offset 700 ms sent:")
    print(show(doc))


def s03_no_taps() -> None:
    heading("S03", "deck uploaded, speaker never taps")
    w, s = words_from([
        ("First I will explain the problem.", 0.8),
        ("Then I will show the numbers.", 0.8),
        ("And finally what we ask from you.", 0.8),
    ])
    doc, pieces = ideal_text(w, s, {"slides": deck(3), "slide_advances": []})
    print(show(doc))
    st = build_slide_transcripts(w, [], deck(3))
    print(f"  per-slide transcripts saved: {[x.get('transcript') for x in st]}")


def s04_revisit() -> None:
    heading("S04", "revisits a slide: 1 → 2 → 1 → 3")
    w, s = words_from([
        ("This is the market.", 0.8),
        ("This is our product.", 0.8),
        ("Back to the market for one more number.", 0.8),
        ("And this is the team.", 0.8),
    ])
    starts = [w[0]["start"], w[4]["start"], w[8]["start"], w[16]["start"]]
    adv = [{"index": i, "t_ms": int(t * 1000)} for i, t in zip([0, 1, 0, 2], starts)]
    doc, _ = ideal_text(w, s, {"slides": deck(3), "slide_advances": adv})
    print(show(doc))


def s05_deckless_long() -> None:
    heading("S05", "no deck, 3-minute monologue with natural pauses")
    sentence = ("We tried three pricing models this year and each one taught us "
                "something about who actually pays")
    w, s = words_from([(sentence, 0.9)] * 24)
    doc, _ = ideal_text(w, s, None)
    paras = doc["paragraphs"] if doc else []
    lens = [p["end"] - p["start"] for p in paras]
    print(f"  {len(paras)} paragraphs, lengths {min(lens)}–{max(lens)} chars, all slide={set(p['slide_index'] for p in paras)}")


def s06_runon() -> None:
    heading("S06", "run-on speech: no punctuation from Whisper, short pauses (<600 ms)")
    text = " ".join(["and then we looked at the data and saw that people drop off"] * 12)
    w, _ = words_from([(text, 0.0)])
    s = [{"text": text, "start": 0, "end": w[-1]["end"]}]   # one segment, no punctuation
    doc, _ = ideal_text(w, s, None)
    first = doc["text"].split("\n\n")[0] if doc else ""
    print(f"  sentence ends in Ideal Text: {doc['text'].count('.') if doc else 0}; first paragraph ({len(first)} chars):")
    print(f"    {first[:160]}…")


def s07_fillers() -> None:
    heading("S07", "fillers: what a live Take sees (no language on pieces) vs language known")
    w, s = words_from([("Um so uh I think, umm, we should, erm, launch in May.", 0.6)])
    for lang in (None, "en"):
        doc, _ = ideal_text(w, s, None, language=lang)
        print(f"  language={lang!s:5} → {doc['text'] if doc else None}")
    w, s = words_from([("Yyy no więc eee myślę że, yyy, powinniśmy zacząć w maju.", 0.6)])
    for lang in (None, "pl"):
        doc, _ = ideal_text(w, s, None, language=lang)
        print(f"  pl language={lang!s:5} → {doc['text'] if doc else None}")
    w, s = words_from([("Ähm also äh wir sollten, ähm, im Mai starten.", 0.6)])
    doc, _ = ideal_text(w, s, None)
    print(f"  de language=None  → {doc['text'] if doc else None}")


def s08_repeats() -> None:
    heading("S08", "immediate repeats: disfluency vs grammatical double words")
    for line in ("We we need to to move faster.",
                 "I had had enough of that.",
                 "He said that that plan would fail.",
                 "It is what it is, is it not?",
                 "Bye bye, see you next week."):
        w, s = words_from([(line, 0.5)])
        doc, _ = ideal_text(w, s, None, language="en")
        print(f"  {line!r:40} → {doc['text'] if doc else None!r}")


def s09_casing() -> None:
    heading("S09", "sentence casing across languages and abbreviations")
    for lang, line in (("en", "we grew. revenue doubled. e.g. in the U.S. it tripled."),
                       ("pl", "zaczęliśmy w maju. świetnie nam poszło. łącznie sto osób."),
                       ("uk", "ми почали в травні. це спрацювало."),
                       ("de", "wir haben es geschafft. über tausend Leute kamen.")):
        w, s = words_from([(line, 0.5)])
        doc, _ = ideal_text(w, s, None, language=lang)
        print(f"  {lang}: {doc['text'] if doc else None}")


def s10_very_long() -> None:
    heading("S10", "very long talk (~55 min of speech) vs the document caps")
    sentence = ("This section walks through the regional numbers one market at a "
                "time so everyone can follow the trend")
    w, s = words_from([(sentence, 0.7)] * 420)
    spoken_chars = sum(len(x["word"]) + 1 for x in w)
    doc, _ = ideal_text(w, s, None)
    kept = len(doc["text"]) if doc else 0
    last_end = doc["pieces"][-1]["end"] if doc else 0
    print(f"  spoken ≈{spoken_chars} chars, minutes ≈{w[-1]['end'] / 60:.0f}; Ideal Text keeps {kept} chars "
          f"({kept * 100 // spoken_chars}%), last piece ends at {last_end}")
    minutes_at_20k = 20000 / (spoken_chars / (w[-1]["end"] / 60))
    print(f"  ideal_text_block then cuts at 20000 (≈{minutes_at_20k:.0f} min at 150 wpm): pieces past it = "
          f"{sum(1 for p in (doc or {}).get('pieces', []) if p['end'] > 20000)}")


def s11_take2_one_slide() -> None:
    heading("S11", "Take 2 re-records only slide 2; the speaker had edited slide 3")
    w1, s1 = words_from([("Slide one first take words.", 1.0), ("Slide two first take words.", 1.0),
                         ("Slide three first take words.", 1.0)])
    adv1 = [{"index": i, "t_ms": int(w1[i * 5]["start"] * 1000)} for i in range(3)]
    t1, _ = ideal_text(w1, s1, {"slides": deck(3), "slide_advances": adv1})
    assert t1
    w2, s2 = words_from([("Slide two said much better now.", 1.0)])
    t2, _ = ideal_text(w2, s2, {"slides": deck(3), "slide_advances": [{"index": 1, "t_ms": 0}]},
                       sid="take-2", take_index=2)
    assert t2
    blocks = t1["text"].split("\n\n")
    edited = "\n\n".join(blocks[:2] + ["Slide three, as I edited it by hand."])
    rb = merge_by_slide(t1["text"], t1, t2["text"], t2, current_text=edited)
    print("  merged:" if rb else "  merge refused")
    if rb:
        for slide, block in zip(rb.slides, rb.text.split("\n\n")):
            print(f"    [slide {slide}] {block}")


def s12_take2_deckless_after_deck() -> None:
    heading("S12", "Take 1 with a deck, Take 2 without one")
    w1, s1 = words_from([("Slide one words.", 1.0), ("Slide two words.", 1.0)])
    adv1 = [{"index": 0, "t_ms": 0}, {"index": 1, "t_ms": int(w1[3]["start"] * 1000)}]
    t1, _ = ideal_text(w1, s1, {"slides": deck(2), "slide_advances": adv1})
    w2, s2 = words_from([("Only the first part again, better.", 1.0)])
    t2, _ = ideal_text(w2, s2, None, sid="take-2", take_index=2)
    assert t1 and t2
    rb = merge_by_slide(t1["text"], t1, t2["text"], t2)
    print(f"  merge_by_slide: {'merged' if rb else 'None (slides unprovable)'}")
    if rb is None:
        rb = follow_the_take(t1["text"], t1, t2["text"], t2)
        print(f"  follow_the_take → whole text is now: {rb.text if rb else None!r}")
        print("  (slide 2's words from Take 1 are no longer in the Ideal Text)")


def s13_helper_words() -> None:
    heading("S13", "helper words: cap and survival across Takes")
    para_t1 = ["We cut onboarding from twelve steps to three and churn halved."]
    for phrase in ("twelve steps · three · churn halved",
                   "cut onboarding from twelve steps to three and churn",
                   "Twelve steps"):
        print(f"  {phrase!r:56} within_cap={within_cap(phrase)!s:5} "
              f"in Take 1={phrase_in_version(phrase, para_t1)!r}")
    para_t2 = ["We went from 12 steps to 3, and churn fell by half."]
    print(f"  same pick vs Take 2 wording (digits, synonyms): "
          f"{phrase_in_version('twelve steps · three · churn halved', para_t2)!r}")


def s14_gate() -> None:
    heading("S14", "speech gate on synthetic audio (16 kHz)")
    sr = 16000
    rng = np.random.default_rng(0)

    def tone(db: float, secs: float) -> np.ndarray:
        amp = 10 ** (db / 20) * np.sqrt(2)
        t = np.arange(int(sr * secs)) / sr
        return (amp * np.sin(2 * np.pi * 180 * t)).astype(np.float32)

    cases = {
        "60 s silence": np.zeros(sr * 60, dtype=np.float32),
        "60 s speech at -30 dBFS": tone(-30, 60),
        "60 s quiet speech at -48 dBFS (far mic)": tone(-48, 60),
        "1 s speech": tone(-25, 1),
        "60 s fan/room noise at -40 dBFS, no speech": (rng.normal(0, 10 ** (-40 / 20), sr * 60)).astype(np.float32),
    }
    for name, sig in cases.items():
        r = evaluate_min_content(sig)
        print(f"  {name:45} ok={r['ok']!s:5} reason={r['reason']} voiced={r['voiced_sec']}s")


def s15_whisper_request() -> None:
    heading("S15", "the Whisper call a live Take makes")
    vocab = [f"TermNumber{i:02d}Xyz" for i in range(40)]
    req = _whisper_request("take.webm", b"x", "audio/webm", vocab, None)
    prompt = req.get("prompt", "")
    print(f"  language passed: {req.get('language')!r}; prompt {len(prompt)} chars "
          f"(≈{len(prompt) // 4} tokens; Whisper reads only the last ~224)")
    print(f"  prompt starts: {prompt[:70]!r}")
    req = _whisper_request("take.webm", b"x", "audio/webm", [], "pl")
    print(f"  with language='pl' (never sent by a live Take): language={req.get('language')!r}, "
          f"prompt={req.get('prompt')!r}")


def s16_unknown_slide() -> None:
    heading("S16", "one piece with an unprovable slide in a decked Take")
    rows = [({"id": "a", "metrics": {"piece": {"slide_index": 1}}}, "words on slide two", 1),
            ({"id": "b", "metrics": {"piece": {}}}, "words with no slide", None),
            ({"id": "c", "metrics": {"piece": {"slide_index": 0}}}, "words on slide one", 0)]
    finished = _finish_document(*_lay_out(rows, "t", 1))
    assert finished
    text, _, paras = finished
    print(f"  paragraph slides in order: {[p['slide_index'] for p in paras]}  text={text!r}")


SCENARIOS: list[Any] = [s01_clean_deck, s02_tap_lag, s03_no_taps, s04_revisit,
                        s05_deckless_long, s06_runon, s07_fillers, s08_repeats,
                        s09_casing, s10_very_long, s11_take2_one_slide,
                        s12_take2_deckless_after_deck, s13_helper_words, s14_gate,
                        s15_whisper_request, s16_unknown_slide]


def main() -> int:
    for scenario in SCENARIOS:
        try:
            scenario()
        except Exception as e:  # a probe reports, it does not stop
            print(f"  !! {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
