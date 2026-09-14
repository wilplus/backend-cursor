"""Production-shaped fixture helpers for the Confident Moment suites.

These live ALONGSIDE the legacy helpers in
`tests/test_mlc3_dark_assignments_postgres.py`; nothing here modifies or
replaces them, and no existing suite is affected. Suites migrate one at a time,
each with its own regression evidence, and the legacy helpers are deleted only
once every dependent suite has moved.

Why a second set exists
-----------------------
The legacy `make_context` builds fixture state with raw positional INSERTs and
follow-up UPDATEs, e.g. `INSERT INTO ml_speakers VALUES (%s)` and a five-value
`processing_policy_versions` insert. Those shapes belong to narrow test-only
copies of the tables. Against the released schema they fail, because the real
tables carry more columns, stricter NOT NULLs, real uniqueness, and MLC-2
append-only triggers that forbid the UPDATE step outright.

Rather than disable those invariants to make tests pass — which would weaken
exactly the properties the tests exist to protect — these helpers construct the
same state the way production does:

* the phase-1 authorization chain through `register_phase1_policy_v1`,
  `activate_phase1_policy_v1` and `accept_phase1_processing_authorization_v1`;
* speaker identity through `register_ml_speaker_principal_v1`;
* consent through `record_mlc2_consent_grant_v1` and
  `create_mlc2_consent_snapshot_v1`;
* evidence, candidates and predictions through the real ingestion path —
  `enqueue_mlc2_outbox_event_v1` → `claim_mlc2_outbox_events_v1` →
  `finalize_mlc2_confidence_frame_v1`.

Rows that have no canonical writer (the product tables: projects, takes,
snippets) are inserted with NAMED columns, in final form, supplying every NOT
NULL column — never inserted blank and patched afterwards.

The returned mapping is key-compatible with the legacy `make_context` result so
that the already-canonical, RPC-only helpers (`observe`, `assign`,
`add_exercise`, `catalogue`, and the D2/D3/D5 helpers) can consume it unchanged.
"""
from __future__ import annotations

import hashlib
from uuid import uuid4

from psycopg2.extras import Json, RealDictCursor

SPEAKER_SPLIT_POLICY = "speaker-sha256-80-10-10-v1"
CONSENT_POLICY_VERSION = "confident-moment-consent-v1"


def query(connection, sql, params=()):
    with connection.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        return cur.fetchall() if cur.description else []


def one(connection, sql, params=()):
    return query(connection, sql, params)[0]


def rpc(connection, name, *args):
    """Invoke a canonical RPC as service_role.

    Names are literals from this checked-in module, never external input.
    """
    query(connection, "SET ROLE service_role")
    try:
        placeholders = ",".join(["%s"] * len(args))
        return one(connection, f"SELECT * FROM public.{name}({placeholders})", args)
    finally:
        query(connection, "RESET ROLE")


def _hash(seed):
    """A deterministic 64-hex value derived from a label."""
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _copy_hash(copy):
    """The exact sha256 of a copy string.

    `register_phase1_policy_v1` recomputes these and raises
    POLICY_COPY_HASH_MISMATCH if they do not match the supplied copy, so the
    fixture must hash the real text rather than invent a value.
    """
    return hashlib.sha256(copy.encode("utf-8")).hexdigest()


PHASE1_PURPOSES = (
    "recording_voice_processing",
    "transcription_feedback",
    "individual_learning_profile",
    "coach_review",
)


def register_policy(connection, *, version=None, actor="confident-moment-fixture",
                    purpose_ids=None, activate=True):
    """Register and activate a phase-1 policy through its canonical writers.

    `purpose_ids` exists so a negative test can prove a phase-2 purpose is
    refused; production callers should leave it at the default.
    """
    version = version or f"confident-moment-policy-{uuid4().hex[:12]}"
    terms_copy = "Fixture terms"
    privacy_copy = "Fixture privacy"
    ai_notice_copy = "Fixture AI notice"
    agreement_copy = "I am 18+ and accept the fixture policy."
    terms, privacy, ai_notice, agreement = (
        _copy_hash(terms_copy), _copy_hash(privacy_copy),
        _copy_hash(ai_notice_copy), _copy_hash(agreement_copy),
    )
    approved_at = "2026-01-01T00:00:00Z"
    purposes = [
        {
            "purpose_id": purpose,
            "lawful_basis_code": "fixture-only",
            "required_for_core_service": True,
            "capability_version": "confident-moment-fixture-v1",
            "reviewed_at": approved_at,
            "retention_control_version": "retention-v1",
            "deletion_control_version": "deletion-v1",
            "rights_control_version": "rights-v1",
        }
        for purpose in (purpose_ids or PHASE1_PURPOSES)
    ]

    def artifact(kind, label, sha, metadata=None):
        return {
            "artifact_kind": kind,
            "version": f"{label}-{version}",
            "approving_authority": "fixture-only",
            "approved_at": approved_at,
            "object_key": f"fixture/{label}",
            "sha256": sha,
            "metadata": metadata or {},
        }

    rpc(
        connection,
        "register_phase1_policy_v1",
        Json({
            "version": version,
            "terms_version": f"terms-{version}", "terms_copy": terms_copy,
            "terms_copy_sha256": terms,
            "privacy_version": f"privacy-{version}",
            "privacy_copy": privacy_copy, "privacy_copy_sha256": privacy,
            "ai_notice_version": f"ai-{version}",
            "ai_notice_copy": ai_notice_copy,
            "ai_notice_copy_sha256": ai_notice,
            "agreement_copy": agreement_copy,
            "agreement_copy_sha256": agreement,
            "allowed_countries": ["pl", "fr"],
        }),
        Json(artifact("product_legal_approval", "legal", _hash("legal"))),
        Json(artifact(
            "power_score_classification", "power", _hash("power"),
            {
                "biometric_identification": False,
                "sex_gender_inference": False,
                "emotion_intention_inference": False,
                "pipeline_version": "voice-confidence-universal-v3",
            },
        )),
        Json(artifact("article_50_assessment", "article50", _hash("article50"))),
        Json(purposes),
        actor,
    )
    if activate:
        rpc(connection, "activate_phase1_policy_v1", version, actor,
            _hash(f"activation-{version}"))
    return {
        "version": version, "terms": terms, "privacy": privacy,
        "ai_notice": ai_notice, "agreement": agreement,
    }


def accept_authorization(connection, principal_id, policy, *, pooled=True):
    """Create the receipt and snapshot through the canonical acceptance RPC."""
    return rpc(
        connection,
        "accept_phase1_processing_authorization_v1",
        principal_id, policy["version"], policy["terms"], policy["privacy"],
        policy["ai_notice"], policy["agreement"], "agree_and_continue", True,
        "pl", "en", "confident-moment-fixture", "2026-01-02T00:00:00Z",
        f"confident-moment-auth-{uuid4()}",
    )


def register_speaker(connection, principal_id, *, identity_hash=None):
    """Bind a speaker identity to a principal through its canonical writer."""
    return rpc(
        connection,
        "register_ml_speaker_principal_v1",
        principal_id, identity_hash or _hash(f"speaker-{uuid4()}"),
        "speaker-resolution-v1", "initial", _hash(f"proof-{uuid4()}"),
        "confident-moment-fixture", SPEAKER_SPLIT_POLICY,
    )


def create_product_rows(connection):
    """Create the exact released v2-session -> attempt -> Take lineage.

    Product tables do not yet expose a canonical writer, so the fixture uses
    named columns and supplies every required value in final form.  Migration
    0297 intentionally uses one identity for the v2 session, durable recording
    attempt, and successful canonical Take.
    """
    ids = {
        name: str(uuid4())
        for name in ("user", "owner", "project", "attempt")
    }
    ids["take"] = ids["attempt"]
    query(
        connection,
        "INSERT INTO auth.users(id,email) VALUES(%s,%s)",
        (ids["user"], f"fixture-{ids['user']}@example.invalid"),
    )
    query(
        connection,
        "INSERT INTO owner_principals(id,guest_secret_hash) VALUES(%s,%s)",
        (ids["owner"], _hash(f"owner-{ids['owner']}")),
    )
    query(
        connection,
        "INSERT INTO projects(id,owner_principal_id,display_name) "
        "VALUES(%s,%s,%s)",
        (ids["project"], ids["owner"], "Production fixture project"),
    )
    query(
        connection,
        "INSERT INTO v2_sessions(id,arc_id,owner_principal_id,user_id,"
        "take_index,recording_kind,project_id,canonical_take_index,"
        "analysis_state) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            ids["attempt"], f"fixture-{ids['attempt']}", ids["owner"],
            ids["user"], 1, "spoken", ids["project"], 1, "processing",
        ),
    )
    query(
        connection,
        "INSERT INTO recording_attempts("
        "id,owner_principal_id,project_id,upload_idempotency_key,"
        "recording_kind,status,attempt_count,provenance_eligible,created_at,"
        "terminal_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,now(),now())",
        (
            ids["attempt"], ids["owner"], ids["project"],
            f"fixture-upload-{ids['attempt']}", "spoken", "succeeded", 1,
            True,
        ),
    )
    query(
        connection,
        "INSERT INTO takes(id,recording_attempt_id,owner_principal_id,"
        "project_id,take_index,completion_hash,completed_at) "
        "VALUES(%s,%s,%s,%s,%s,%s,now())",
        (
            ids["take"], ids["attempt"], ids["owner"], ids["project"], 1,
            _hash(f"completion-{ids['attempt']}"),
        ),
    )
    return ids


def grant_consent(connection, principal_id, recording_attempt_id, take_id):
    """Record a consent grant and the per-take snapshot the frame requires."""
    legal_approval_id = str(uuid4())
    existing = query(
        connection,
        "SELECT version FROM ml_consent_policies WHERE version=%s",
        (CONSENT_POLICY_VERSION,),
    )
    if not existing:
        query(
            connection,
            "INSERT INTO ml_product_legal_approvals(id,approval_reference,"
            "approved_copy_sha256,onboarding_copy,consent_policy_version,"
            "terms_version,privacy_policy_version,approving_authority,"
            "approved_at,jurisdictions,article_6_basis,article_9_treatment,"
            "evidence_object_key,evidence_sha256) VALUES(%s,%s,%s,%s,%s,%s,%s,"
            "%s,%s,%s,%s,%s,%s,%s)",
            (
                legal_approval_id, "CONFIDENT-MOMENT-FIXTURE-ONLY",
                _hash("consent-copy"), "Fixture onboarding copy",
                CONSENT_POLICY_VERSION, "terms-v1", "privacy-v1",
                "fixture-only", "2026-01-01T00:00:00Z", ["EU"], "6(1)(a)",
                "9(2)(a)_when_special_category", "fixture/consent.json",
                _hash("consent-evidence"),
            ),
        )
        query(
            connection,
            "INSERT INTO ml_consent_policies(version,product_legal_approval_id,"
            "required_for_service,bundled_ui,active_from) "
            "VALUES(%s,%s,true,true,%s)",
            (CONSENT_POLICY_VERSION, legal_approval_id, "2026-01-01T00:00:00Z"),
        )
    rpc(
        connection,
        "record_mlc2_consent_grant_v1",
        principal_id, CONSENT_POLICY_VERSION, "EU", "terms-v1", "privacy-v1",
        "/fixture", "confident-moment-fixture",
        Json({
            "accepted": True,
            "copy_sha256": _hash("consent-copy"),
            "purposes": ["personalized_coaching", "pooled_model_improvement"],
        }),
        "2026-01-02T00:00:00Z", True, f"confident-moment-consent-{uuid4()}",
    )
    return rpc(
        connection,
        "create_mlc2_consent_snapshot_v1",
        principal_id, recording_attempt_id, take_id, None,
    )


def issue_service_authority(connection, principal_id, take_id, recording_id,
                            *, operation_kind="source_audio_lineage"):
    """Issue a processing authorization SNAPSHOT through its canonical writer.

    `accept_phase1_processing_authorization_v1` writes only the receipt. The
    per-operation snapshot that downstream guards bind to is written by
    `issue_exercise_service_authority_v1`; the legacy helpers inserted that row
    by hand, which is why they drifted from the released chain.
    """
    return rpc(
        connection,
        "issue_exercise_service_authority_v1",
        principal_id, take_id, recording_id, operation_kind,
        f"confident-moment-authority-{uuid4()}",
    )
