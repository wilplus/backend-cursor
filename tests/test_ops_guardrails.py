"""P0/P2 ops sweep 2026-08-03 — upload defenses, bucket split, secrets, Sentry.

Four independent guardrails, one module because they ship as one sweep:

  * ``services.upload_guard``      — bounded read + wall-clock deadline
  * ``services.lab_audio_storage`` — the lab-audio bucket split
  * ``services.secrets``           — secret resolution + the boot audit
  * Sentry sampling                — no longer hardcoded to 1.0

The lab-storage tests are the load-bearing ones: they assert the split is
INERT until both env vars are set, which is the property that makes this
mergeable while the live loop is running.
"""
from __future__ import annotations

import io
import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("JWT_SECRET", "test-secret-value-not-a-placeholder")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-key")

from services.upload_guard import (  # noqa: E402
    Deadline, DeadlineExceeded, UploadTooLarge, deadline_for, read_capped,
)


class _FakeUpload:
    """Minimal Werkzeug FileStorage stand-in."""

    def __init__(self, data: bytes):
        self.stream = io.BytesIO(data)


class ReadCappedTests(unittest.TestCase):

    def test_reads_a_normal_upload_whole(self):
        payload = b"a" * 1024
        self.assertEqual(read_capped(_FakeUpload(payload), 4096), payload)

    def test_refuses_at_one_byte_over(self):
        with self.assertRaises(UploadTooLarge):
            read_capped(_FakeUpload(b"a" * 101), 100)

    def test_exactly_at_the_cap_is_allowed(self):
        self.assertEqual(len(read_capped(_FakeUpload(b"a" * 100), 100)), 100)

    def test_empty_upload_returns_empty_not_an_error(self):
        # The route decides whether empty is a 400 — the reader doesn't.
        self.assertEqual(read_capped(_FakeUpload(b""), 100), b"")

    def test_oversized_body_is_not_fully_buffered(self):
        """The point of the cap: a lying Content-Length can't OOM a worker.

        We hand it 50x the cap and assert it stopped reading early, which
        is what ``.read()`` with no argument failed to do.
        """
        big = _FakeUpload(b"x" * 50_000)
        with self.assertRaises(UploadTooLarge):
            read_capped(big, 1_000, chunk_size=256)
        self.assertLessEqual(big.stream.tell(), 1_500)

    def test_rejects_a_nonsense_cap(self):
        with self.assertRaises(ValueError):
            read_capped(_FakeUpload(b"x"), 0)


class DeadlineTests(unittest.TestCase):

    def test_fresh_deadline_does_not_fire(self):
        Deadline(60, label="t").check("stage-1")  # must not raise

    def test_spent_deadline_raises_with_the_stage_named(self):
        d = Deadline(60, label="t")
        d.started_at -= 61
        with self.assertRaises(DeadlineExceeded) as ctx:
            d.check("transcribe")
        self.assertEqual(ctx.exception.stage, "transcribe")

    def test_zero_disables_the_guard(self):
        d = Deadline(0, label="t")
        d.started_at -= 10_000
        self.assertFalse(d.enabled)
        d.check("anything")  # must not raise
        self.assertEqual(d.remaining(), float("inf"))

    def test_remaining_shrinks_and_floors_at_zero(self):
        d = Deadline(60, label="t")
        self.assertLessEqual(d.remaining(), 60)
        d.started_at -= 120
        self.assertEqual(d.remaining(), 0.0)

    def test_deadline_for_reads_config(self):
        self.assertIsInstance(deadline_for("lab-upload").budget, float)

    def test_deadline_for_survives_a_broken_config(self):
        with patch("config.Config", side_effect=RuntimeError("boom")):
            self.assertFalse(deadline_for("lab-upload").enabled)


class LabAudioStorageTests(unittest.TestCase):
    """The split must be INERT until deliberately switched on."""

    def setUp(self):
        import services.lab_audio_storage as mod

        self.mod = mod
        mod._reset_config_cache()

    def tearDown(self):
        self.mod._reset_config_cache()

    def _cfg(self, **overrides):
        cfg = MagicMock()
        cfg.R2_LAB_AUDIO_BUCKET = overrides.get("bucket", "")
        cfg.R2_LAB_AUDIO_PUBLIC_BASE_URL = overrides.get("public_base", "")
        cfg.COACH_FEEDBACK_VIDEO_BUCKET = "coach_feedback_videos"
        cfg.R2_PUBLIC_BASE_URL = overrides.get("coach_base", "https://coach.example")
        cfg.R2_ACCOUNT_ID = "acct"
        cfg.R2_ACCESS_KEY_ID = "akid"
        cfg.R2_SECRET_ACCESS_KEY = "secret"
        return cfg

    def test_inert_when_nothing_is_configured(self):
        with patch.object(self.mod, "_config", return_value=self._cfg()):
            self.assertFalse(self.mod.lab_audio_segregated())
            self.assertEqual(self.mod.target_bucket(), "coach_feedback_videos")

    def test_inert_when_only_the_bucket_is_set(self):
        """Bucket without public base = new bytes, stale URLs = 404s."""
        with patch.object(self.mod, "_config",
                          return_value=self._cfg(bucket="willab-lab-audio")):
            with patch("services.coach_video_storage.coach_videos_use_r2",
                       return_value=True):
                self.assertFalse(self.mod.lab_audio_segregated())
                self.assertEqual(self.mod.target_bucket(),
                                 "coach_feedback_videos")

    def test_active_when_both_are_set(self):
        cfg = self._cfg(bucket="willab-lab-audio",
                        public_base="https://lab-audio.example")
        with patch.object(self.mod, "_config", return_value=cfg):
            with patch("services.coach_video_storage.coach_videos_use_r2",
                       return_value=True):
                self.assertTrue(self.mod.lab_audio_segregated())
                self.assertEqual(self.mod.target_bucket(), "willab-lab-audio")

    def test_pre_cutover_write_uses_the_old_path_unchanged(self):
        with patch.object(self.mod, "_config", return_value=self._cfg()):
            with patch("services.coach_video_storage.put_coach_object_bytes") as put:
                bucket = self.mod.put_lab_audio_bytes("k/a.webm", b"b", "audio/webm")
        put.assert_called_once()
        self.assertEqual(bucket, "coach_feedback_videos")

    def test_post_cutover_write_targets_the_lab_bucket(self):
        cfg = self._cfg(bucket="willab-lab-audio",
                        public_base="https://lab-audio.example")
        client = MagicMock()
        with patch.object(self.mod, "_config", return_value=cfg), \
                patch.object(self.mod, "_client", return_value=client), \
                patch("services.coach_video_storage.coach_videos_use_r2",
                      return_value=True):
            bucket = self.mod.put_lab_audio_bytes("k/a.webm", b"b", "audio/webm")
        self.assertEqual(bucket, "willab-lab-audio")
        self.assertEqual(client.put_object.call_args.kwargs["Bucket"],
                         "willab-lab-audio")

    def test_public_url_follows_the_bytes(self):
        cfg = self._cfg(bucket="willab-lab-audio",
                        public_base="https://lab-audio.example")
        with patch.object(self.mod, "_config", return_value=cfg), \
                patch("services.coach_video_storage.coach_videos_use_r2",
                      return_value=True):
            self.assertEqual(self.mod.lab_audio_public_url("k/a.webm"),
                             "https://lab-audio.example/k/a.webm")
        with patch.object(self.mod, "_config", return_value=self._cfg()):
            self.assertEqual(self.mod.lab_audio_public_url("k/a.webm"),
                             "https://coach.example/k/a.webm")

    def test_read_falls_back_to_the_coach_bucket(self):
        """A take written BEFORE the cutover must still be readable."""
        cfg = self._cfg(bucket="willab-lab-audio",
                        public_base="https://lab-audio.example")
        client = MagicMock()

        def _get(Bucket, Key):
            if Bucket == "willab-lab-audio":
                raise Exception("NoSuchKey")
            return {"Body": io.BytesIO(b"legacy-bytes")}

        client.get_object.side_effect = _get
        with patch.object(self.mod, "_config", return_value=cfg), \
                patch.object(self.mod, "_client", return_value=client), \
                patch("services.coach_video_storage.coach_videos_use_r2",
                      return_value=True), \
                patch("services.audio_storage.audio_bucket_name",
                      return_value=""):
            self.assertEqual(self.mod.get_lab_audio_bytes("old/take.webm"),
                             b"legacy-bytes")

    def test_bucket_hint_is_tried_first(self):
        cfg = self._cfg(bucket="willab-lab-audio",
                        public_base="https://lab-audio.example")
        client = MagicMock()
        client.get_object.return_value = {"Body": io.BytesIO(b"ok")}
        with patch.object(self.mod, "_config", return_value=cfg), \
                patch.object(self.mod, "_client", return_value=client), \
                patch("services.coach_video_storage.coach_videos_use_r2",
                      return_value=True), \
                patch("services.audio_storage.audio_bucket_name",
                      return_value=""):
            self.mod.get_lab_audio_bytes("k.webm",
                                         bucket_hint="coach_feedback_videos")
        self.assertEqual(client.get_object.call_args_list[0].kwargs["Bucket"],
                         "coach_feedback_videos")

    def test_exhausting_every_bucket_raises_without_leaking_config(self):
        cfg = self._cfg(bucket="willab-lab-audio",
                        public_base="https://lab-audio.example")
        client = MagicMock()
        client.get_object.side_effect = Exception("NoSuchKey")
        with patch.object(self.mod, "_config", return_value=cfg), \
                patch.object(self.mod, "_client", return_value=client), \
                patch("services.coach_video_storage.coach_videos_use_r2",
                      return_value=True), \
                patch("services.audio_storage.audio_bucket_name",
                      return_value=""):
            with self.assertRaises(FileNotFoundError) as ctx:
                self.mod.get_lab_audio_bytes("gone.webm")
        msg = str(ctx.exception)
        self.assertIn("gone.webm", msg)
        self.assertNotIn("secret", msg)


class SecretsTests(unittest.TestCase):

    def setUp(self):
        self._saved = dict(os.environ)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._saved)

    def test_file_indirection_wins_over_the_env_var(self):
        import tempfile

        from services.secrets import resolve

        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
            fh.write("from-the-file\n")   # trailing newline must be stripped
            path = fh.name
        os.environ["DEMO_SECRET"] = "from-the-env"
        os.environ["DEMO_SECRET_FILE"] = path
        try:
            self.assertEqual(resolve("DEMO_SECRET"), "from-the-file")
        finally:
            os.unlink(path)

    def test_unreadable_file_does_not_silently_fall_back(self):
        # Falling back to a stale env value is how the WRONG credential
        # gets used with nobody noticing.
        from services.secrets import resolve

        os.environ["DEMO_SECRET"] = "from-the-env"
        os.environ["DEMO_SECRET_FILE"] = "/nonexistent/path/secret"
        self.assertIsNone(resolve("DEMO_SECRET"))

    def test_env_var_is_used_when_no_file_is_configured(self):
        from services.secrets import resolve

        os.environ.pop("DEMO_SECRET_FILE", None)
        os.environ["DEMO_SECRET"] = '  "quoted-value"  '
        self.assertEqual(resolve("DEMO_SECRET"), "quoted-value")

    def test_placeholders_are_detected(self):
        from services.secrets import looks_like_placeholder

        self.assertTrue(looks_like_placeholder("ci-placeholder-secret"))
        self.assertTrue(looks_like_placeholder("CHANGEME"))
        self.assertFalse(looks_like_placeholder("sk-proj-9a8f7e6d5c4b3a21"))

    def test_production_placeholder_is_an_error(self):
        from services.secrets import audit

        os.environ.update({
            "ENV": "production",
            "SUPABASE_URL": "https://ci-placeholder.invalid",
            "SUPABASE_SERVICE_ROLE_KEY": "ci-placeholder-key",
            "OPENAI_API_KEY": "sk-proj-realish-key-9a8f7e6d5c4b",
        })
        result = audit()
        self.assertTrue(any("SUPABASE_URL" in e for e in result["errors"]))

    def test_development_placeholder_is_only_a_warning(self):
        from services.secrets import audit

        os.environ.update({
            "ENV": "development",
            "SUPABASE_URL": "https://ci-placeholder.invalid",
        })
        result = audit()
        self.assertEqual(result["errors"], [])

    def test_staging_refuses_a_live_stripe_key(self):
        from services.secrets import audit

        os.environ.update({
            "ENV": "staging",
            "STRIPE_SECRET_KEY": "sk_live_abcdefghijklmnopqrst",
        })
        self.assertTrue(any("LIVE key" in e for e in audit()["errors"]))

    def test_staging_refuses_the_production_database(self):
        from services.secrets import audit

        os.environ.update({
            "ENV": "staging",
            "SUPABASE_URL": "https://prod.supabase.co",
            "PRODUCTION_SUPABASE_URL": "https://prod.supabase.co",
        })
        self.assertTrue(any("production database" in e
                            for e in audit()["errors"]))

    def test_staging_refuses_unredirected_email(self):
        from services.secrets import audit

        os.environ.update({"ENV": "staging", "SEND_EMAILS": "true"})
        os.environ.pop("EMAIL_REDIRECT_TO", None)
        self.assertTrue(any("EMAIL_REDIRECT_TO" in e
                            for e in audit()["errors"]))

    def test_staging_accepts_a_redirected_setup(self):
        from services.secrets import audit

        os.environ.update({
            "ENV": "staging", "SEND_EMAILS": "true",
            "EMAIL_REDIRECT_TO": "qa@willpowerlab.com",
            "SUPABASE_URL": "https://staging.supabase.co",
            "STRIPE_SECRET_KEY": "sk_test_abcdefghijklmnopqrst",
        })
        os.environ.pop("PRODUCTION_SUPABASE_URL", None)
        self.assertEqual(audit()["errors"], [])

    def test_enforce_crashes_production_on_an_error(self):
        from services.secrets import enforce_at_boot

        os.environ.update({"ENV": "production", "SUPABASE_URL": "",
                           "SUPABASE_SERVICE_ROLE_KEY": "",
                           "OPENAI_API_KEY": ""})
        with self.assertRaises(RuntimeError):
            enforce_at_boot()

    def test_enforce_only_logs_in_development(self):
        from services.secrets import enforce_at_boot

        os.environ.update({"ENV": "development", "SUPABASE_URL": "",
                           "SUPABASE_SERVICE_ROLE_KEY": "",
                           "OPENAI_API_KEY": ""})
        enforce_at_boot()  # must not raise

    def test_audit_never_contains_a_secret_value(self):
        from services.secrets import audit

        # Distinctive value that can't collide with the finding's own
        # wording (a value of "short" matches the word "shorter").
        os.environ.update({
            "ENV": "production",
            "SUPABASE_SERVICE_ROLE_KEY": "SEKRITZ9",   # too short -> a finding
            "SUPABASE_URL": "https://real.supabase.co",
            "OPENAI_API_KEY": "sk-proj-realish-key-9a8f7e6d5c4b",
        })
        result = audit()
        self.assertTrue(any("SUPABASE_SERVICE_ROLE_KEY" in e
                            for e in result["errors"]))
        self.assertNotIn("SEKRITZ9", str(result))

    def test_redact_shows_only_the_tail(self):
        from services.secrets import redact

        out = redact("sk-proj-abcdefghijklmnop")
        self.assertNotIn("abcdefghijkl", out)
        self.assertTrue(out.endswith("mnop"))
        self.assertEqual(redact(None), "<unset>")


class SentrySamplingTests(unittest.TestCase):
    """The rate must be config-driven, and cheap by default."""

    def _config_with(self, env: str, **overrides):
        import importlib

        saved = dict(os.environ)
        os.environ["ENV"] = env
        for k, v in overrides.items():
            os.environ[k] = v
        try:
            import config as config_module

            importlib.reload(config_module)
            return config_module.Config()
        finally:
            os.environ.clear()
            os.environ.update(saved)
            import config as config_module

            importlib.reload(config_module)

    def test_production_default_is_sampled_not_everything(self):
        cfg = self._config_with("production")
        self.assertGreater(cfg.SENTRY_TRACES_SAMPLE_RATE, 0)
        self.assertLess(cfg.SENTRY_TRACES_SAMPLE_RATE, 1.0)

    def test_development_sends_no_traces(self):
        self.assertEqual(
            self._config_with("development").SENTRY_TRACES_SAMPLE_RATE, 0.0)

    def test_rate_is_overridable(self):
        cfg = self._config_with("production", SENTRY_TRACES_SAMPLE_RATE="0.25")
        self.assertEqual(cfg.SENTRY_TRACES_SAMPLE_RATE, 0.25)

    def test_malformed_rate_falls_back_instead_of_crashing_import(self):
        cfg = self._config_with("production", SENTRY_TRACES_SAMPLE_RATE="banana")
        self.assertEqual(cfg.SENTRY_TRACES_SAMPLE_RATE, 0.05)

    def test_profiling_is_off_by_default(self):
        self.assertEqual(
            self._config_with("production").SENTRY_PROFILES_SAMPLE_RATE, 0.0)

    def test_no_module_hardcodes_a_full_trace_rate(self):
        for path in ("app.py", "worker.py"):
            with open(path, encoding="utf-8") as fh:
                for n, line in enumerate(fh, 1):
                    if "traces_sample_rate" in line and "=" in line:
                        self.assertNotIn(
                            "1.0", line,
                            f"{path}:{n} hardcodes a 100% trace rate")


class EmailRedirectTests(unittest.TestCase):
    """Staging must not be able to email real users."""

    def test_non_production_redirects_the_recipient(self):
        import services.email_service as mod

        sent = {}

        def _send(params):
            sent.update(params)
            return {"id": "e1"}

        cfg = mod.config
        with patch.object(cfg, "EMAIL_REDIRECT_TO", "qa@willpowerlab.com",
                          create=True), \
                patch.object(cfg, "SEND_EMAILS", True), \
                patch.object(cfg, "RESEND_API_KEY", "re_testkey"), \
                patch.object(cfg, "ENV", "staging"), \
                patch.object(mod.resend.Emails, "send", _send):
            mod.send_email_resend(to="real.student@example.com",
                                  subject="Your readout", html="<p>hi</p>")
        self.assertEqual(sent["to"], ["qa@willpowerlab.com"])
        self.assertIn("real.student@example.com", sent["subject"])

    def test_production_is_never_redirected(self):
        import services.email_service as mod

        sent = {}

        def _send(params):
            sent.update(params)
            return {"id": "e1"}

        cfg = mod.config
        with patch.object(cfg, "EMAIL_REDIRECT_TO", "qa@willpowerlab.com",
                          create=True), \
                patch.object(cfg, "SEND_EMAILS", True), \
                patch.object(cfg, "RESEND_API_KEY", "re_testkey"), \
                patch.object(cfg, "ENV", "production"), \
                patch.object(mod.resend.Emails, "send", _send):
            mod.send_email_resend(to="real.student@example.com",
                                  subject="Your readout", html="<p>hi</p>")
        self.assertEqual(sent["to"], ["real.student@example.com"])


if __name__ == "__main__":
    unittest.main()
