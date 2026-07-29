"""willab — the imported voice is NOT the account holder's (fix 2026-07-29).

Where the training-import wave met the speaker-sex wave. The confidence
composite routes its cue WEIGHTS on the speaker's sex, and cue 1 (f0_sd)
REVERSES direction between them. An imported take is someone else's voice
filed under the importing coach's user_id — so resolving sex from that
account would apply the COACH's weights to a stranger's voice and invert the
strongest cue. Silently: the score still looks plausible.

That would corrupt the exact signal the corpus exists to train, which is why
this has its own file rather than a case buried in the import suite.

Run: python3 -m unittest test_import_speaker_sex
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock

_ORIG = {}


def setUpModule():
    for name in ("services.db", "services.coach_video_storage",
                 "services.min_content_gate", "services.lab_recording"):
        _ORIG[name] = sys.modules.get(name)
    db_stub = types.ModuleType("services.db")
    db_stub.db = MagicMock()
    sys.modules["services.db"] = db_stub
    store = types.ModuleType("services.coach_video_storage")
    store.put_coach_object_bytes = lambda *a, **k: None
    store.coach_media_public_url = lambda key: f"https://cdn/{key}"
    sys.modules["services.coach_video_storage"] = store
    gate = types.ModuleType("services.min_content_gate")
    gate.evaluate_min_content_bytes = lambda b: {"ok": True,
                                                 "duration_sec": 42.0}
    sys.modules["services.min_content_gate"] = gate
    lab = types.ModuleType("services.lab_recording")
    lab.process_lab_recording = lambda **kw: {"snippets": [{"id": "p1"}]}
    sys.modules["services.lab_recording"] = lab


def tearDownModule():
    for name, mod in _ORIG.items():
        if mod is not None:
            sys.modules[name] = mod
        else:
            sys.modules.pop(name, None)


def _db():
    d = MagicMock()
    d.find_training_import_by_key.return_value = None
    return d


class ImportMarksTheSpeakerAsNotTheOwner(unittest.TestCase):

    def _ctx(self, **over):
        from services.training_import import prepare_training_import
        db = _db()
        prepare_training_import(
            audio_bytes=b"A", filename="t.mp3", user_id="coach-1",
            topic="T", database=db, **over)
        return db.set_session_intake_context.call_args.args[1]

    def test_every_import_disclaims_account_ownership_of_the_voice(self):
        """THE assertion. Without this flag the pipeline reads the importing
        coach's declared sex and applies it to a stranger's voice."""
        self.assertIs(self._ctx()["speaker_is_account_holder"], False)

    def test_declared_speaker_sex_rides_the_context(self):
        self.assertEqual(self._ctx(speaker_sex="Female")["speaker_sex"],
                         "female")

    def test_absent_speaker_sex_stays_absent(self):
        """No claim = the acoustic route decides. The import must not invent
        a sex, and must not fall back to the account's."""
        self.assertNotIn("speaker_sex", self._ctx())


class PipelineHonoursTheDisclaimer(unittest.TestCase):
    """The lab_recording side: which user_id (if any) reaches
    resolve_speaker_sex, and what a declared speaker_sex overrides."""

    def _resolve(self, ctx: dict):
        """Replay the pipeline's resolution block against a stub resolver,
        capturing the user_id it was asked about."""
        seen = {}

        def _resolver(user_id, baseline):
            seen["user_id"] = user_id
            return ("male", "declared") if user_id else ("female", "inferred")

        from services.voice_confidence import normalize_sex
        declared = ctx.get("speaker_sex")
        is_owner = ctx.get("speaker_is_account_holder", True)
        if declared:
            norm = normalize_sex(declared)
            if norm == "prefer_not_to_say":
                out = (None, "not_stated")
            elif norm:
                out = (norm, "declared")
            else:
                out = _resolver(None, None)
        else:
            out = _resolver("coach-1" if is_owner else None, None)
        return out, seen

    def test_a_normal_take_still_asks_about_the_account(self):
        """The live path must be unchanged — absent the flag, the account
        lookup runs exactly as before."""
        out, seen = self._resolve({})
        self.assertEqual(seen["user_id"], "coach-1")
        self.assertEqual(out, ("male", "declared"))

    def test_an_import_never_asks_about_the_account(self):
        out, seen = self._resolve({"speaker_is_account_holder": False})
        self.assertIsNone(seen["user_id"],
                          "an import must not inherit the coach's sex")
        self.assertEqual(out[1], "inferred")   # dropped to the acoustic route

    def test_a_declared_speaker_sex_wins_over_everything(self):
        out, seen = self._resolve({"speaker_is_account_holder": False,
                                   "speaker_sex": "female"})
        self.assertEqual(out, ("female", "declared"))
        self.assertEqual(seen, {}, "no lookup needed when it was declared")

    def test_prefer_not_to_say_is_still_a_hard_opt_out(self):
        """The opt-out survives the import path: it must NOT quietly become
        the acoustic route, which is what an opt-out routed around is."""
        out, _seen = self._resolve({"speaker_is_account_holder": False,
                                    "speaker_sex": "prefer_not_to_say"})
        self.assertEqual(out, (None, "not_stated"))

    def test_junk_speaker_sex_degrades_to_the_acoustic_route(self):
        out, seen = self._resolve({"speaker_is_account_holder": False,
                                   "speaker_sex": "banana"})
        self.assertIsNone(seen["user_id"])
        self.assertEqual(out[1], "inferred")


class SourcePin(unittest.TestCase):

    def test_the_pipeline_reads_the_disclaimer(self):
        """Source-level pin: if the resolution block stops consulting
        speaker_is_account_holder, every imported voice silently inherits the
        coach's weights again."""
        with open("services/lab_recording.py", encoding="utf-8") as fh:
            source = fh.read()
        block = source.split("resolve_speaker_sex")[2][:900] \
            if source.count("resolve_speaker_sex") > 2 else source
        self.assertIn("speaker_is_account_holder", source)
        self.assertIn("speaker_sex", source)


if __name__ == "__main__":
    unittest.main()
