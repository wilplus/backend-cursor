"""The database itself refuses an ungated model promotion.

LEGACY-1 (blocker) and R-13, audit 2026-09-22. The Python gate in
`services/runtime_model_gate.py` is the boundary a request crosses. This is
the boundary a PSQL SESSION crosses — an operator, a script, or anything else
holding the Supabase service-role key, which is the population the finding is
actually about: `runtime_config` had no RLS, no trigger and `GRANT ALL` to
`service_role`, so one INSERT changed which model composes a speaker's Take-1
Ideal Text within the sixty-second cache.

Asserting the trigger by reading the migration text proves only that somebody
typed it. These cases execute it.

The target must be a disposable local database whose name starts with
``willab_model_gate_``. Nothing here activates anything: every case below
expects a REFUSAL, and the one success path writes a fake model id into a
throwaway table.
"""
from __future__ import annotations

import json
import os

import psycopg2
import pytest

DSN = os.environ.get("RUNTIME_MODEL_GATE_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable model-gate rehearsal only"
)

GATED_KEYS = (
    "openai_surface_model_ideal_text",
    "openai_surface_model_say_it_stronger",
    "openai_surface_model_coach_comment_draft",
    "openai_chat_model",
    "openai_copilot_model",
)
PROMPT_HASH = "a" * 64


@pytest.fixture
def db():
    parsed = psycopg2.extensions.parse_dsn(DSN)
    if not parsed.get("dbname", "").startswith("willab_model_gate_"):
        raise RuntimeError("Refusing a non-disposable database")
    if not parsed.get("host", "").startswith(
        ("/tmp/willab-", "/private/tmp/willab-")
    ):
        raise RuntimeError("Refusing a database outside the rehearsal socket")
    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    try:
        yield conn
    finally:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM public.runtime_config")
        conn.close()


def _promote(conn, key, value, metadata):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT public.promote_runtime_surface_model_v1(%s, %s, %s, %s)",
            (key, value, "tests", json.dumps(metadata)),
        )
        return cur.fetchone()[0]


class TestTheDirectWriteIsRefused:
    @pytest.mark.parametrize("key", GATED_KEYS)
    def test_a_direct_insert_of_a_model_key_raises(self, db, key):
        """The finding, executed: this INSERT used to succeed."""
        with pytest.raises(psycopg2.errors.RaiseException) as caught:
            with db.cursor() as cur:
                cur.execute(
                    "INSERT INTO public.runtime_config(key, value) VALUES (%s, %s)",
                    (key, "ft:a-model-nobody-approved"),
                )
        assert "RUNTIME_MODEL_PROMOTION_NOT_PERMITTED" in str(caught.value)

    def test_a_direct_update_of_a_model_key_raises(self, db):
        key = "openai_surface_model_ideal_text"
        _promote(db, key, "ft:approved", {"prompt_lock_sha256": PROMPT_HASH})
        with pytest.raises(psycopg2.errors.RaiseException) as caught:
            with db.cursor() as cur:
                cur.execute(
                    "UPDATE public.runtime_config SET value = %s WHERE key = %s",
                    ("ft:swapped-underneath", key),
                )
        assert "RUNTIME_MODEL_PROMOTION_NOT_PERMITTED" in str(caught.value)
        with db.cursor() as cur:
            cur.execute("SELECT value FROM public.runtime_config WHERE key = %s", (key,))
            assert cur.fetchone()[0] == "ft:approved"

    def test_an_unrelated_key_is_untouched(self, db):
        """The guard is narrow on purpose: this table has other tenants."""
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO public.runtime_config(key, value) VALUES (%s, %s)",
                ("some_unrelated_toggle", "on"),
            )
            cur.execute(
                "SELECT value FROM public.runtime_config WHERE key = %s",
                ("some_unrelated_toggle",),
            )
            assert cur.fetchone()[0] == "on"


class TestTheOneWriterValidates:
    def test_a_key_outside_the_allowlist_is_refused(self, db):
        with pytest.raises(psycopg2.errors.RaiseException) as caught:
            _promote(db, "openai_surface_model_moment_suggestion", "ft:x",
                     {"prompt_lock_sha256": PROMPT_HASH})
        assert "RUNTIME_MODEL_KEY_NOT_ENUMERATED" in str(caught.value)

    @pytest.mark.parametrize("metadata", [
        {},
        {"prompt_lock_sha256": ""},
        {"prompt_lock_sha256": "not-a-digest"},
        {"prompt_lock_sha256": "A" * 63},
    ])
    def test_a_promotion_without_a_prompt_binding_is_refused(self, db, metadata):
        """H-1: a promoted model carries the prompts it was gated under."""
        with pytest.raises(psycopg2.errors.RaiseException) as caught:
            _promote(db, "openai_surface_model_say_it_stronger", "ft:x", metadata)
        assert "RUNTIME_MODEL_PROMPT_LOCK_REQUIRED" in str(caught.value)

    def test_an_empty_model_id_is_refused(self, db):
        with pytest.raises(psycopg2.errors.RaiseException) as caught:
            _promote(db, "openai_surface_model_ideal_text", "   ",
                     {"prompt_lock_sha256": PROMPT_HASH})
        assert "RUNTIME_MODEL_VALUE_REQUIRED" in str(caught.value)

    def test_a_complete_promotion_is_stored_with_its_binding(self, db):
        row = _promote(
            db, "openai_surface_model_ideal_text", " ft:approved ",
            {"prompt_lock_sha256": PROMPT_HASH, "surface": "ideal_text"},
        )
        assert row["value"] == "ft:approved"
        assert row["metadata"]["prompt_lock_sha256"] == PROMPT_HASH

    def test_the_permission_does_not_outlive_its_transaction(self, db):
        """A promotion must not leave the door open behind it."""
        _promote(db, "openai_surface_model_ideal_text", "ft:approved",
                 {"prompt_lock_sha256": PROMPT_HASH})
        with pytest.raises(psycopg2.errors.RaiseException):
            with db.cursor() as cur:
                cur.execute(
                    "INSERT INTO public.runtime_config(key, value) VALUES (%s, %s)",
                    ("openai_chat_model", "ft:rides-in-behind"),
                )

    def test_one_permission_does_not_cover_another_key(self, db):
        """Set for key A, used for key B, inside one transaction."""
        conn = psycopg2.connect(DSN)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT public.promote_runtime_surface_model_v1(%s, %s, %s, %s)",
                    ("openai_surface_model_ideal_text", "ft:approved", "tests",
                     json.dumps({"prompt_lock_sha256": PROMPT_HASH})),
                )
                with pytest.raises(psycopg2.errors.RaiseException):
                    cur.execute(
                        "INSERT INTO public.runtime_config(key, value) "
                        "VALUES (%s, %s)",
                        ("openai_chat_model", "ft:rides-in-behind"),
                    )
            conn.rollback()
        finally:
            conn.close()


class TestTheGrantsAreLockedDown:
    @pytest.mark.parametrize("role", ["anon", "authenticated"])
    def test_the_writer_is_not_callable_by_a_browser_role(self, db, role):
        with db.cursor() as cur:
            cur.execute(
                "SELECT has_function_privilege(%s, "
                "'public.promote_runtime_surface_model_v1(text,text,text,jsonb)', "
                "'EXECUTE')", (role,),
            )
            assert cur.fetchone()[0] is False

    def test_service_role_may_call_the_writer(self, db):
        with db.cursor() as cur:
            cur.execute(
                "SELECT has_function_privilege('service_role', "
                "'public.promote_runtime_surface_model_v1(text,text,text,jsonb)', "
                "'EXECUTE')",
            )
            assert cur.fetchone()[0] is True

    def test_the_writer_pins_its_search_path(self, db):
        with db.cursor() as cur:
            cur.execute(
                "SELECT proconfig FROM pg_proc WHERE proname = "
                "'promote_runtime_surface_model_v1'",
            )
            assert any("search_path=" in s for s in (cur.fetchone()[0] or []))
