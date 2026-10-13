#!/usr/bin/env python3
"""Manual smoke test of the AI voice against the real ElevenLabs account.

Run it yourself, on your own machine, with YOUR OWN consented voice. It is
never run by CI and never committed with audio. Nothing it makes is stored
in the app's database.

    set -a; source .env; set +a          # ELEVENLABS_API_KEY (and OPENAI_API_KEY)
    .venv-ci/bin/python scripts/ai_voice_smoke.py \
        --sample ~/Documents/willab-private/voice-sample-artur.m4a \
        --i-consent-this-is-my-own-voice

It: reads the plan's credits; makes one Instant Voice Clone from the
sample; generates the same sentence three ways (pace, pause, stress) with
Eleven v4 through the app's own prompt builder; checks each clip with the
app's validator (words re-heard by Whisper when OPENAI_API_KEY is set);
writes the clips and a report next to the sample, with the latency of every
stage and end to end per clip; and deletes the clone (unless --keep-voice),
even when a step fails. Listen to the clips: the quality call is yours.

This calls ElevenLabs directly, outside the app's processing permit: it is
the founder's own consented voice, on their own machine, and nothing it
makes touches the app's database. It never runs for a speaker.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SENTENCE = ("We think the timing matters because the window closes "
            "once the incumbents match our price")


def _transcribe(audio: bytes):
    if not os.getenv("OPENAI_API_KEY"):
        return None
    from services.snippet_transcription import transcribe_snippet_bytes
    return transcribe_snippet_bytes(audio, "smoke.mp3", language_hint="en")


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _one_clip(client, voice_id: str, args, problem: str, phrase, out_dir: Path) -> dict:
    """One clip, timed per stage as the app's job runs them: build the
    request, generate, re-hear (Whisper), validate; end_to_end is the sum."""
    from services import ai_voice_prompt
    from services.ai_voice_validator import validate
    clock: dict[str, int] = {}
    t0 = started = time.monotonic()
    exercise = {"exercise": problem, "target_phrase": phrase if problem != "pace" else None}
    request = ai_voice_prompt.build(sentence=args.sentence, exercise=exercise,
                                    practice_id=f"smoke-{problem}")
    clock["build"] = _ms(started)
    started = time.monotonic()
    speech = client.speak(voice_id=voice_id, body=request["body"])
    clock["generation"] = _ms(started)
    (out_dir / f"{problem}.mp3").write_bytes(speech.audio)
    started = time.monotonic()
    heard = _transcribe(speech.audio)
    clock["re_transcription"] = _ms(started)
    started = time.monotonic()
    result = validate(audio=speech.audio, transcription=heard,
                      spoken_words=request["spoken_words"], exercise=exercise,
                      original_wpm=args.original_wpm, original_duration_s=None)
    clock["validation"] = _ms(started)
    clock["end_to_end"] = _ms(t0)
    return {"prepared_text": request["prepared_text"], "latency_ms": clock,
            "character_cost": speech.character_cost, "passed": result["passed"],
            "failed_checks": result["failed_checks"], "validation": result,
            "re_heard": heard is not None}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", required=True, type=Path)
    parser.add_argument("--sentence", default=SENTENCE)
    parser.add_argument("--original-wpm", type=float, default=175.0)
    parser.add_argument("--i-consent-this-is-my-own-voice", action="store_true")
    parser.add_argument("--keep-voice", action="store_true")
    args = parser.parse_args()
    if not args.i_consent_this_is_my_own_voice:
        print("Refusing: pass --i-consent-this-is-my-own-voice (your own voice only).")
        return 2

    from services import ai_voice_prompt, ai_voice_severity
    from services.elevenlabs_client import ElevenLabsClient, VoiceProviderError

    client = ElevenLabsClient()
    out_dir = args.sample.expanduser().resolve().parent / "ai-voice-smoke"
    out_dir.mkdir(exist_ok=True)
    report: dict = {"model": ai_voice_prompt.Config.ELEVENLABS_MODEL_ID}
    voice_id = None
    try:
        report["plan_before"] = client.subscription()
        sample = args.sample.expanduser().read_bytes()
        started = time.monotonic()
        voice_id = client.create_voice(
            name="willab-smoke", sample=sample, filename=args.sample.name,
            content_type=mimetypes.guess_type(args.sample.name)[0] or "audio/mpeg")
        report["clone_ms"] = _ms(started)
        phrase = ai_voice_severity.target_phrase(args.sentence)
        for problem in ("pace", "pause", "stress"):
            report[problem] = _one_clip(client, voice_id, args, problem, phrase, out_dir)
            row = report[problem]
            print(f"{problem:6s} {'PASS' if row['passed'] else 'FAIL'} "
                  f"{row['failed_checks']} {row['latency_ms']}")
        report["plan_after"] = client.subscription()
    except VoiceProviderError as error:
        print(f"ElevenLabs refused: {error.kind} (status {error.status})")
        report["error"] = {"kind": error.kind, "status": error.status}
    finally:
        # The test clone never outlives the run, even when a step failed.
        if voice_id and not args.keep_voice:
            try:
                client.delete_voice(voice_id)
                report["voice_deleted"] = not client.voice_exists(voice_id)
            except VoiceProviderError as error:
                report["voice_deleted"] = False
                print(f"Clone NOT deleted ({error.kind}): delete it in ElevenLabs.")
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, default=str))
    print(f"Clips and report in {out_dir}")
    return 1 if "error" in report else 0


if __name__ == "__main__":
    raise SystemExit(main())
