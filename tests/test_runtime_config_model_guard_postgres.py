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
