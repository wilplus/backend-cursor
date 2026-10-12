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
writes the clips and a report next to the sample; and deletes the clone
(unless --keep-voice). Listen to the clips: the quality call is yours.
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
    from services.ai_voice_validator import validate
    from services.elevenlabs_client import ElevenLabsClient, VoiceProviderError

    client = ElevenLabsClient()
    out_dir = args.sample.expanduser().resolve().parent / "ai-voice-smoke"
    out_dir.mkdir(exist_ok=True)
    report: dict = {"model": ai_voice_prompt.Config.ELEVENLABS_MODEL_ID}
    try:
        report["plan_before"] = client.subscription()
        sample = args.sample.expanduser().read_bytes()
        started = time.monotonic()
        voice_id = client.create_voice(
            name="willab-smoke", sample=sample, filename=args.sample.name,
            content_type=mimetypes.guess_type(args.sample.name)[0] or "audio/mpeg")
        report["clone_ms"] = int((time.monotonic() - started) * 1000)
        phrase = ai_voice_severity.target_phrase(args.sentence)
        for problem in ("pace", "pause", "stress"):
            exercise = {"exercise": problem,
                        "target_phrase": phrase if problem != "pace" else None}
            request = ai_voice_prompt.build(sentence=args.sentence, exercise=exercise,
                                            practice_id=f"smoke-{problem}")
            started = time.monotonic()
            speech = client.speak(voice_id=voice_id, body=request["body"])
            generated_ms = int((time.monotonic() - started) * 1000)
            (out_dir / f"{problem}.mp3").write_bytes(speech.audio)
            result = validate(audio=speech.audio, transcription=_transcribe(speech.audio),
                              spoken_words=request["spoken_words"], exercise=exercise,
                              original_wpm=args.original_wpm, original_duration_s=None)
            report[problem] = {"prepared_text": request["prepared_text"],
                               "generation_ms": generated_ms,
                               "character_cost": speech.character_cost,
                               "validation": result}
            print(f"{problem:6s} {'PASS' if result['passed'] else 'FAIL'} "
                  f"{result['failed_checks']} {generated_ms} ms")
        if not args.keep_voice:
            client.delete_voice(voice_id)
            report["voice_deleted"] = not client.voice_exists(voice_id)
        report["plan_after"] = client.subscription()
    except VoiceProviderError as error:
        print(f"ElevenLabs refused: {error.kind} (status {error.status})")
        return 1
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, default=str))
    print(f"Clips and report in {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
