"""
STORY    As the founder, I want the database itself to refuse an unapproved
         model setting, so that even someone with the service key cannot
         change the model behind a speaker's Ideal Text.
OUTCOME
  O1  Writing any of the gated model settings straight into the database
      is refused with "model promotion not permitted".
PROVES   O1 -> TestTheDirectWriteIsRefused::test_a_direct_insert_of_a_model_key_raises
WHY      Audit 2026-09-22 (LEGACY-1, R-13): one INSERT could change the Ideal
         Text model within a minute.
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
