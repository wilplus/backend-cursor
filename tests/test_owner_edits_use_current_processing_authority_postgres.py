"""STORY    As a speaker, I can save and reload my own words after accepting
          the current agreement, without joining the retired coaching loop.
OUTCOME  O1 A committed edit reloads with the same Paragraph and revision.
         O2 Missing/stale agreement or a service block refuses the write.
         O3 Another owner cannot edit my project; strict F2 access stays closed.
PROVES   O1 -> test_current_authority_saves_and_reloads_without_coaching_enrollment
         O2 -> test_current_processing_authority_is_required,
               test_a_claimed_guests_account_purge_still_blocks_an_owner_edit
         O3 -> test_another_owner_cannot_edit_the_project, O1's strict F2 check
WHY      Contract 9, N663, N664; retired MLC-3 loop (contract 66).
"""
from __future__ import annotations

import os
import uuid

import psycopg2
import pytest

from tests.confident_moment_production_fixtures import (
    accept_authorization, one, query, register_policy,
)
from tests.test_a_take_rewrite_is_a_paragraph_revision_postgres import (
    _speaker_with_a_published_take_two,
)
from tests.test_take_two_rewrites_an_edited_slide_postgres import _database
from tests.test_v3_reaches_every_speaker_postgres import _active_contract
from tests.test_phase1_processing_postgres import _intake

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(not DSN, reason="disposable released rehearsal only")


@pytest.fixture
def speaker():
    parsed = psycopg2.extensions.parse_dsn(DSN)
    if not parsed.get("dbname", "").startswith("willab_confident_moment_"):
        raise RuntimeError("Refusing a non-disposable database")
    conn = psycopg2.connect(DSN)
    try:
        with conn.cursor() as cur:
            _active_contract(cur)
            user, project, _take = _speaker_with_a_published_take_two(cur)
        principal = one(conn, "SELECT id FROM owner_principals WHERE user_id=%s", (user,))["id"]
        policy = register_policy(conn)
        accept_authorization(conn, principal, policy)
        yield conn, user, project, principal
    finally:
        conn.rollback()
        conn.close()


def _save(speaker, *, user=None):
    from services.ideal_text_user_edit import save_user_edit

    conn, owner, project, _principal = speaker
    part = str(uuid.uuid4())
    query(conn, "SET LOCAL ROLE service_role")
    return save_user_edit(
        _database(conn), arc_id=project, user_id=user or owner,
        body={"text": "My revised words.", "version": 1,
              "expected_user_text_revision": None,
              "expected_user_text_sha256": None,
              "idempotency_key": str(uuid.uuid4()),
              "parts": {"expected_parts": [], "desired_parts": [
                  {"position": 0, "part_id": part, "text": "My revised words."}]}},
    )


def test_current_authority_saves_and_reloads_without_coaching_enrollment(speaker):
    conn, user, project, principal = speaker
    before = one(conn, "SELECT count(*) n FROM mlc3_service_enrollment_revisions")["n"]
    result = _save(speaker)
    conn.commit()
    # A new connection/repository reads committed storage, not editor state.
    with psycopg2.connect(DSN) as reload:
        saved = _database(reload).get_user_ideal_edit(project, user)
        assert (saved["text"], saved["version"]) == ("My revised words.", 1)
        paragraph = one(reload, "SELECT id::text, text FROM ideal_text_part WHERE arc_id=%s", (project,))
        assert paragraph["id"] == result["part_revisions"][0]["part_id"]
        assert paragraph["text"] == saved["text"]
        assert one(reload, "SELECT count(*) n FROM mlc3_service_enrollment_revisions")["n"] == before
        with pytest.raises(psycopg2.Error, match="MLC3_"):
            query(reload, "SELECT require_mlc3_service_access_v2(%s,NULL,NULL)", (principal,))


@pytest.mark.parametrize("refusal", ["new policy", "service block"])
def test_current_processing_authority_is_required(speaker, refusal):
    from services.refusal import Refusal

    conn, _user, project, principal = speaker
    if refusal == "new policy":
        register_policy(conn)
        expected = "PROCESSING_AUTHORIZATION_REQUIRED"
    else:
        query(conn, "INSERT INTO processing_service_blocks(acquisition_principal_id, block_kind, reason_code) VALUES(%s,'restriction','test')", (principal,))
        expected = "PROCESSING_SERVICE_BLOCKED"
    with pytest.raises(Refusal) as refused:
        _save(speaker)
    assert refused.value.body["code"] == expected
    assert refused.value.status == 403
    conn.rollback()
    assert one(conn, "SELECT count(*) n FROM user_arc_ideal_notes WHERE arc_id=%s", (project,))["n"] == 0


def test_another_owner_cannot_edit_the_project(speaker):
    with pytest.raises(psycopg2.Error):
        _save(speaker, user=str(uuid.uuid4()))


def test_a_claimed_guests_account_purge_still_blocks_an_owner_edit(speaker):
    from services.refusal import Refusal

    conn, user, _project, principal = speaker
    guest = str(uuid.uuid4())
    query(conn, "INSERT INTO owner_principals(id,guest_secret_hash) VALUES(%s,%s)", (guest, "b" * 64))
    policy = register_policy(conn)
    accept_authorization(conn, guest, policy)
    _intake(conn, guest)
    query(conn, """INSERT INTO owner_claim_events(
        source_owner_principal_id,target_owner_principal_id,claimed_user_id,
        claim_proof_hash,idempotency_key,source_created_at)
        VALUES(%s,%s,%s,%s,%s,now())""", (guest, principal, user, "c" * 64, str(uuid.uuid4())))
    query(conn, """INSERT INTO data_purge_requests(
        acquisition_principal_id,trigger_kind,idempotency_key)
        VALUES(%s,'account_deletion',%s)""", (guest, str(uuid.uuid4())))
    with pytest.raises(Refusal) as refused:
        _save(speaker)
    assert refused.value.body["code"] == "MLC3_SERVICE_PRINCIPAL_NOT_ALLOWED"
