"""The scheduled clean-up against a real schema (migrations 0423 and 0426;
services/retention_cleaner.py; founder 2026-10-05, decisions log N48.4 Q16 A
and N50).

What it proves, on the released lane:
  * the report, a dry run and the founder's script count the same lines, and
    on a world built for it those lines are exactly the rows that are due --
    and they are the report of 2026-10-05's numbers, except where 0423
    refined them (a processing job deletion evidence points at is kept) and
    0426 changed them (the founder's bug list is not a log, N50 C4 B; the
    financial records whose five years have ended are rule 4, N50 P7);
  * a live request is refused while RETENTION_CLEANER_LIVE is False, and
    deletes nothing;
  * with the key patched on, a live run deletes exactly those rows and
    objects: an unclaimed guest through the account purge, an idle
    account's recording with its voice measurements (the measurements go
    first, the event names the run), the four logs' old rows, the financial
    records past their five years (the year read in Warsaw time; an account
    under erasure left to it) -- and nothing that is not due, nothing
    retained, and never the founder's bug list;
  * a second run finds nothing left to do; a recording whose object will
    not go keeps its event back but never its measurements; and the guards
    0423 opens open for a live run only;
  * rule 1 is a purge: without the purge kill switch no guest is erased
    (rules 2 to 4 still run), and a guest whose erasure stopped for review
    is left for a person, never run again.

Every case runs in ONE transaction that is rolled back, so nothing it writes
reaches the next case or the next suite in the lane. The cleaner's own code
runs through the SQL client tests/test_account_deletion_starts_postgres.py
built for the purge: its PostgREST calls become SQL, as service_role. The
world is set in 2001 (AS_OF): every row the other suites write is dated
today, so nothing of theirs is ever due here, and the cases can say
"exactly".

Stand-ins, each named: object storage is faked (this lane has no R2); every
retention rule the purge can ask for is seeded active, as production's are
(tests/test_take_purge_postgres.py); the tables this lane does not carry are
built from their own migrations (token_ledger's beside a one-column
stand-in for the account table it alters, v2_student_details, which predates
the migrations directory); 0426 is applied again inside the case, so its
door to the two financial tables, guarded on them existing, opens as it does
in production; and the grants Supabase gives service_role by default are
given, on the other tables only: rule 4 deletes with 0426's door alone.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras
import pytest
from psycopg2 import sql

from services import data_purge
from services import retention_cleaner as rc
from tests import test_account_deletion_starts_postgres as base
from tests import test_take_purge_postgres as takes

DSN = base.DSN
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)

ROOT = Path(__file__).resolve().parents[1]
AS_OF_AT = datetime(2001, 6, 1, tzinfo=timezone.utc)
AS_OF = AS_OF_AT.isoformat()

#: Tables production has and this lane does not, built from their own files.
TABLE_FILES = (
    "add_dev_bugs.sql", "add_life_push_reminders.sql",
    "add_admin_annotations_log.sql", "add_candidate_windows.sql",
    "add_user_sniper_profile.sql", "add_arc_part_acoustics.sql",
    "add_user_acoustic_baseline.sql", "add_dimension_evaluations.sql",
    "add_dimension_evaluations_snippet_grain.sql",
    "add_llm_usage.sql", "add_token_pricing.sql",
)
#: Rule 4's migration, applied again once its two tables exist here.
FINANCIAL_MIGRATION = "financial_records_go_after_five_years.sql"
#: What Supabase grants service_role on every public table by default.
SUPABASE_DEFAULT_GRANTS = (
    "processing_jobs", "dev_bugs", "life_reminder_log", "admin_annotations_log",
    "candidate_windows", "session_sniper_metrics", "arc_part_acoustics",
    "user_acoustic_baseline", "dimension_evaluations", "snippets",
)
#: The report as the founder ran it on 2026-10-05 (N47), before 0423.
REPORT_2026_10_05 = """
WITH cut AS (
    SELECT %(as_of)s::timestamptz - interval '30 days'  AS guest_cut,
           %(as_of)s::timestamptz - interval '12 months' AS audio_cut,
           %(as_of)s::timestamptz - interval '90 days'  AS log_cut
),
old_guests AS (
    SELECT p.id FROM public.owner_principals p, cut
     WHERE p.user_id IS NULL AND p.guest_secret_hash IS NOT NULL
       AND p.claimed_at IS NULL AND p.created_at < cut.guest_cut
       AND NOT EXISTS (SELECT 1 FROM public.owner_claim_events e
                        WHERE e.source_owner_principal_id = p.id)
),
live_audio AS (
    SELECT o.id, o.created_at,
           COALESCE(op.claimed_by_owner_principal_id, op.id) AS owner_id
      FROM public.processing_audio_objects o
      JOIN public.owner_principals op ON op.id = o.acquisition_principal_id
     WHERE o.deleted_at IS NULL
),
unused_audio AS (
    SELECT a.id FROM live_audio a, cut
     WHERE a.created_at < cut.audio_cut
       AND NOT EXISTS (SELECT 1 FROM public.projects pr
                        WHERE pr.owner_principal_id = a.owner_id
                          AND pr.updated_at >= cut.audio_cut)
)
SELECT 1 AS rule, 'unclaimed guests older than 30 days' AS would_delete,
       (SELECT count(*) FROM old_guests) AS how_many
UNION ALL
SELECT 1, 'their recordings (audio files)',
       (SELECT count(*) FROM public.processing_audio_objects o
          JOIN old_guests g ON g.id = o.acquisition_principal_id
         WHERE o.deleted_at IS NULL)
UNION ALL
SELECT 2, 'audio files not used for 12 months', (SELECT count(*) FROM unused_audio)
UNION ALL
SELECT 3, 'log rows older than 90 days: processing_jobs',
       (SELECT count(*) FROM public.processing_jobs, cut WHERE created_at < cut.log_cut)
UNION ALL
SELECT 3, 'log rows older than 90 days: dev_bugs',
       (SELECT count(*) FROM public.dev_bugs, cut WHERE created_at < cut.log_cut)
UNION ALL
SELECT 3, 'log rows older than 90 days: life_reminder_log',
       (SELECT count(*) FROM public.life_reminder_log, cut WHERE created_at < cut.log_cut)
UNION ALL
SELECT 3, 'log rows older than 90 days: admin_annotations_log',
       (SELECT count(*) FROM public.admin_annotations_log, cut WHERE created_at < cut.log_cut)
UNION ALL
SELECT 3, 'log rows older than 90 days: mlc3_service_backpressure_events',
       (SELECT count(*) FROM public.mlc3_service_backpressure_events, cut
         WHERE created_at < cut.log_cut)
"""

MEASURES = "voice measurements with that audio: "
LOGS = "log rows older than 90 days: "
KEPT = "log rows older than 90 days kept, deletion evidence points at them: "
FIN = "financial records whose five years have ended: "
#: The lines the world below must produce at AS_OF, and nothing else.
EXPECTED = {
    (1, "unclaimed guests older than 30 days"): 1,
    (1, "their recordings (audio files)"): 1,
    (2, "audio files not used for 12 months"): 1,
    (2, MEASURES + "acoustic_feature_snapshots.features"): 1,
    (2, MEASURES + "arc_part_acoustics"): 1,
    (2, MEASURES + "candidate_windows.metrics"): 1,
    (2, MEASURES + "dimension_evaluations"): 2,
    (2, MEASURES + "session_sniper_metrics"): 1,
    (2, MEASURES + "snippets.metrics"): 2,
    (2, MEASURES + "user_acoustic_baseline"): 1,
    (2, MEASURES + "v2_sessions.voice_measures"): 1,
    (3, LOGS + "admin_annotations_log"): 1,
    (3, LOGS + "life_reminder_log"): 1,
    (3, LOGS + "mlc3_service_backpressure_events"): 1,
    (3, LOGS + "processing_jobs"): 1,
    (3, KEPT + "processing_jobs"): 2,
    (4, FIN + "llm_usage"): 1,
    (4, FIN + "token_ledger"): 2,
}


# ── The SQL client, with the one PostgREST call the purge never makes ───────

class _Query(base._Query):
    """A DELETE with `returning=minimal` reads nothing back, so it needs no
    SELECT on the rows' other columns (0423 grants a log table only id and
    created_at)."""

    def delete(self, **kwargs):
        returning = kwargs.get("returning")
        self.deleting = True
        self.minimal = getattr(returning, "value", returning) == "minimal"
        return self

    def execute(self):
        if not (self.deleting and getattr(self, "minimal", False)):
            return super().execute()
        where, args = [], []
        for column, op, value in self.filters:
            if op == "=":
                where.append(sql.SQL("{}::text = %s").format(sql.Identifier(column)))
                args.append(str(value))
            else:
                where.append(sql.SQL("{}::text = ANY(%s)").format(sql.Identifier(column)))
                args.append([str(v) for v in value])
        assert where, "an unfiltered DELETE never reaches the database"
        statement = sql.SQL("DELETE FROM public.{} WHERE {}").format(
            sql.Identifier(self.relation), sql.SQL(" AND ").join(where))
        self.client.fetch(statement, args)
        return base._Result([])


class _SqlClient(base._SqlClient):
    """Each call is its own request, as through PostgREST: the case runs in
    one transaction, so every request gets a savepoint, and a request that
    fails (the purge expects some to, and reads the error) undoes only
    itself."""

    def table(self, relation):
        return _Query(self, relation)

    def fetch(self, query, args):
        with self.connection.cursor(
            cursor_factory=psycopg2.extras.RealDictCursor,
        ) as cur:
            cur.execute("SAVEPOINT postgrest_request")
            try:
                cur.execute("SET ROLE service_role")
                cur.execute(query, args)
                rows = ([dict(row) for row in cur.fetchall()]
                        if cur.description else [])
                cur.execute("RESET ROLE")
                cur.execute("RELEASE SAVEPOINT postgrest_request")
                return rows
            except Exception:
                cur.execute("ROLLBACK TO SAVEPOINT postgrest_request")
                raise


class _Database:
    def __init__(self, connection) -> None:
        self.client = _SqlClient(connection)


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def db():
    """One transaction per case, rolled back: nothing reaches the lane."""
    parsed = psycopg2.extensions.parse_dsn(DSN)
    if not parsed.get("dbname", "").startswith("willab_confident_moment_"):
        raise RuntimeError("Refusing a non-disposable database")
    conn = psycopg2.connect(DSN)
    conn.autocommit = False
    try:
        _schema(conn)
        yield conn
    finally:
        conn.rollback()
        conn.close()


@pytest.fixture
def storage(monkeypatch):
    """Object storage, faked for both the cleaner and the account purge."""
    state = {"deleted": [], "absent": False, "refuse": set()}

    def delete(key, *, bucket, storage_provider, expected_sha256):
        if key in state["refuse"]:
            raise ValueError("object checksum does not match purge inventory")
        state["deleted"].append(key)
        return True

    def absent(key, *, bucket, storage_provider):
        return state["absent"]

    for module in (rc, data_purge):
        monkeypatch.setattr(module, "delete_verified_lab_audio_object", delete)
        monkeypatch.setattr(module, "verify_lab_audio_object_absent", absent)
    return state


@pytest.fixture
def key_on(monkeypatch):
    """The founder's key, patched on for this case only."""
    monkeypatch.setattr(rc, "RETENTION_CLEANER_LIVE", True)


def _without_transaction(text: str) -> str:
    """A migration's own BEGIN/COMMIT would end the case's transaction."""
    return re.sub(r"(?im)^\s*(BEGIN|COMMIT)\s*;\s*$", "", text)


def _schema(db) -> None:
    with db.cursor() as cur:
        # The account table token_ledger's migration alters; production's
        # predates the migrations directory. Only the key it is read by.
        cur.execute("""CREATE TABLE IF NOT EXISTS public.v2_student_details (
                           user_id text PRIMARY KEY)""")
        for name in TABLE_FILES:
            text = (ROOT / "migrations" / name).read_text()
            cur.execute(_without_transaction(text))
        # 0426 ran in the lane before its two tables existed here; in
        # production they did. Again, so its door opens as it does there.
        cur.execute(_without_transaction(
            (ROOT / "migrations" / FINANCIAL_MIGRATION).read_text()))
        # 0298's claimed-guest shape, which this lane predates: the column
        # and the identity check production has.
        cur.execute("""
            ALTER TABLE public.owner_principals
                ADD COLUMN IF NOT EXISTS claimed_by_owner_principal_id uuid NULL;
            ALTER TABLE public.owner_principals
                DROP CONSTRAINT IF EXISTS owner_principal_identity_check;
            ALTER TABLE public.owner_principals
                ADD CONSTRAINT owner_principal_identity_check CHECK (
                    (user_id IS NOT NULL AND guest_secret_hash IS NULL
                     AND claimed_by_owner_principal_id IS NULL)
                    OR (user_id IS NULL AND guest_secret_hash IS NOT NULL
                        AND claimed_by_owner_principal_id IS NULL
                        AND claimed_at IS NULL)
                    OR (user_id IS NULL AND guest_secret_hash IS NULL
                        AND claimed_by_owner_principal_id IS NOT NULL
                        AND claimed_at IS NOT NULL));
            ALTER TABLE public.v2_sessions
                ADD COLUMN IF NOT EXISTS global_wpm double precision,
                ADD COLUMN IF NOT EXISTS global_pause_ms double precision,
                ADD COLUMN IF NOT EXISTS global_dynamic_db double precision,
                ADD COLUMN IF NOT EXISTS global_pitch_center double precision,
                ADD COLUMN IF NOT EXISTS global_energy double precision,
                ADD COLUMN IF NOT EXISTS global_fillers integer,
                ADD COLUMN IF NOT EXISTS kpi_score double precision""")
        cur.execute(sql.SQL(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON {} TO service_role").format(
                sql.SQL(", ").join(sql.Identifier("public", t)
                                   for t in SUPABASE_DEFAULT_GRANTS)))
        # What tests/test_take_purge_postgres.py gives the purge, where this
        # lane carries the table (a suite run alone may not have built it).
        cur.execute("""
            ALTER TABLE IF EXISTS public.recordings
                ADD COLUMN IF NOT EXISTS session_v2_id UUID,
                ADD COLUMN IF NOT EXISTS session_id UUID;
            ALTER TABLE IF EXISTS public.training_labels
                ADD COLUMN IF NOT EXISTS session_id UUID""")
        for table in ("v2_sessions", "projects", "ideal_text_document_generations"):
            cur.execute("SELECT to_regclass(%s) IS NOT NULL", (f"public.{table}",))
            if cur.fetchone()[0]:
                cur.execute(sql.SQL(
                    "GRANT SELECT, INSERT, UPDATE, DELETE ON {} TO service_role"
                ).format(sql.Identifier("public", table)))
    takes._seed_every_retention_rule(db)


def _one(db, statement, args=()):
    return base._one(db, statement, args)


def _rows(db, statement, args=()) -> list[dict]:
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(statement, args)
        return [dict(row) for row in cur.fetchall()]


def _at(days: float) -> datetime:
    return AS_OF_AT - timedelta(days=days)


# ── The world ───────────────────────────────────────────────────────────────

def _person(db, kind: str, *, created: float, claimed_by: dict | None = None) -> dict:
    if kind == "account":
        user = _one(db, "INSERT INTO auth.users (id) VALUES (gen_random_uuid()) RETURNING id")
        principal = _one(db, """
            INSERT INTO public.owner_principals (id, user_id, created_at)
            VALUES (gen_random_uuid(), %s, %s) RETURNING id""", (user, _at(created)))
        return {"principal": str(principal), "user": str(user)}
    if kind == "guest":
        principal = _one(db, """
            INSERT INTO public.owner_principals (id, guest_secret_hash, created_at)
            VALUES (gen_random_uuid(), %s, %s) RETURNING id""",
            (uuid.uuid4().hex * 2, _at(created)))
        return {"principal": str(principal), "user": None}
    assert kind == "claimed_guest" and claimed_by
    principal = _one(db, """
        INSERT INTO public.owner_principals (
            id, claimed_at, claimed_by_owner_principal_id, created_at)
        VALUES (gen_random_uuid(), %s, %s, %s) RETURNING id""",
        (_at(created - 1), claimed_by["principal"], _at(created)))
    _one(db, """
        INSERT INTO public.owner_claim_events (
            source_owner_principal_id, target_owner_principal_id,
            claimed_user_id, claim_proof_hash, idempotency_key,
            source_created_at, claimed_at)
        VALUES (%s, %s, %s, repeat('c', 64), %s, %s, %s) RETURNING id""",
        (principal, claimed_by["principal"], claimed_by["user"],
         f"claim-{uuid.uuid4()}", _at(created), _at(created - 1)))
    return {"principal": str(principal), "user": None}


def _project(db, owner: dict, *, touched: float) -> str:
    return str(_one(db, """
        INSERT INTO public.projects (id, owner_principal_id, display_name,
                                     created_at, updated_at)
        VALUES (gen_random_uuid(), %s, 'Q3 pitch', %s, %s) RETURNING id""",
        (owner["principal"], _at(touched + 1), _at(touched))))


def _recording(db, *, acquirer: dict, owner: dict, made: float,
               project: str) -> dict:
    """One Take with its canonical intake, as the live intake leaves it: the
    recording attempt is the Take session (finalize_phase1_recording_intake_v1)."""
    take = str(_one(db, """
        INSERT INTO public.v2_sessions (
            id, user_id, owner_principal_id, project_id, arc_id, take_index)
        VALUES (gen_random_uuid(), %s, %s, %s, %s, 1) RETURNING id""",
        (owner["user"] or str(uuid.uuid4()), owner["principal"], project, project)))
    policy = _one(db, """
        INSERT INTO public.processing_policy_versions (
            id, version, status, terms_version, terms_copy, terms_copy_sha256,
            privacy_version, privacy_copy, privacy_copy_sha256,
            ai_notice_version, ai_notice_copy, ai_notice_copy_sha256,
            agreement_copy, agreement_copy_sha256, allowed_countries, created_by)
        VALUES (gen_random_uuid(), 'retention-' || gen_random_uuid(), 'draft',
                'terms-v1', 'terms', repeat('1', 64), 'privacy-v1', 'privacy',
                repeat('2', 64), 'ai-v1', 'ai', repeat('3', 64), 'agreement',
                repeat('4', 64), ARRAY['PL'], 'rehearsal')
        RETURNING id""")
    receipt = _one(db, """
        INSERT INTO public.processing_authorization_receipts (
            id, acquisition_principal_id, policy_id, idempotency_key,
            explicit_action, age_18_attested, country_of_residence, locale,
            client_version, accepted_at, evidence_sha256)
        VALUES (gen_random_uuid(), %s, %s, %s, 'agree_and_continue', true,
                'PL', 'en', 'rehearsal', %s, repeat('5', 64))
        RETURNING id""", (acquirer["principal"], policy, str(uuid.uuid4()), _at(made)))
    snapshot = _one(db, """
        INSERT INTO public.processing_authorization_snapshots (
            id, acquisition_principal_id, receipt_id, policy_id, purpose_id,
            operation_kind, source_take_id, authority_evidence_sha256)
        VALUES (gen_random_uuid(), %s, %s, %s, 'recording_voice_processing',
                'recording_transcription_ranking_feedback', %s, repeat('6', 64))
        RETURNING id""", (acquirer["principal"], receipt, policy, take))
    recording = str(_one(db, """
        INSERT INTO public.recordings (id) VALUES (gen_random_uuid()) RETURNING id"""))
    _one(db, """
        INSERT INTO public.processing_recording_attempts (
            id, acquisition_principal_id, project_id, recording_id,
            upload_idempotency_key, authorization_snapshot_id, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (take, acquirer["principal"], project, recording, str(uuid.uuid4()),
         snapshot, _at(made)))
    key = f"{acquirer['principal']}/{take}.wav"
    audio = str(_one(db, """
        INSERT INTO public.processing_audio_objects (
            acquisition_principal_id, recording_attempt_id, storage_provider,
            bucket, object_key, byte_size, content_type, exact_bytes_sha256,
            verified_at, verification_method, created_at)
        VALUES (%s, %s, 'r2', 'take-audio', %s, 21, 'audio/wav', repeat('7', 64),
                %s, 'read_after_write_sha256', %s)
        RETURNING id""", (acquirer["principal"], take, key, _at(made), _at(made))))
    return {"take": take, "project": project, "recording": recording,
            "audio": audio, "key": key, "owner": owner}


def _measurements(db, rec: dict) -> None:
    """Voice measurements of one Take, in every store 0423 names."""
    take, owner = rec["take"], rec["owner"]
    for start in (0, 4000):
        _one(db, """
            INSERT INTO public.snippets (id, session_id, recording_id,
                start_offset_ms, duration_ms, transcript, metrics)
            VALUES (gen_random_uuid(), %s, %s, %s, 4000, 'We cut churn by a third.',
                    '{"wpm": 141.0, "pause_ms": 380.0, "f0_sd": 2.4}'::jsonb)
            RETURNING id""", (take, rec["recording"], start))
    _one(db, """
        INSERT INTO public.candidate_windows (session_id, recording_id,
            start_offset_ms, metrics, transcript)
        VALUES (%s, %s, 0, '{"dynamic_db": 11.2}'::jsonb, 'We cut churn.')
        RETURNING id""", (take, rec["recording"]))
    _one(db, """
        UPDATE public.v2_sessions SET global_wpm = 141, global_pause_ms = 380,
               global_dynamic_db = 11.2, global_pitch_center = 4.1,
               global_energy = 0.6, global_fillers = 3, kpi_score = 71
         WHERE id = %s RETURNING id""", (take,))
    _one(db, """
        INSERT INTO public.session_sniper_metrics (session_id, user_id, wpm, pause_ms)
        VALUES (%s, %s, 141, 380) RETURNING session_id""", (take, owner["user"]))
    for dimension in ("wpm", "pitch_center"):
        _one(db, """
            INSERT INTO public.dimension_evaluations (recording_id, session_id,
                user_id, dimension_id, raw_value, benchmark_tier, benchmark_version)
            VALUES (%s, %s, %s, %s, 1.5, 'T1', 'v1') RETURNING id""",
            (rec["recording"], take, owner["user"], dimension))
    span = _one(db, """
        INSERT INTO public.evidence_spans (id, owner_principal_id, project_id,
            take_id, evidence_kind, task_type, start_ms, end_ms, evidence_hash,
            input_hash)
        VALUES (gen_random_uuid(), %s, %s, %s, 'audio_interval',
                'confidence_classification', 0, 4000, %s, repeat('8', 64))
        RETURNING id""", (owner["principal"], rec["project"], take, uuid.uuid4().hex * 2))
    _one(db, """
        INSERT INTO public.acoustic_feature_snapshots (id, evidence_span_id,
            owner_principal_id, feature_schema_version, speaker_baseline_version,
            features, input_hash, code_commit)
        VALUES (gen_random_uuid(), %s, %s, 'v1', 'b1', '{"f0_sd": 2.4}'::jsonb,
                repeat('9', 64), 'c1') RETURNING id""", (span, owner["principal"]))
    _one(db, """
        INSERT INTO public.arc_part_acoustics (part_id, arc_id, user_id, ema_z,
            detector_version)
        VALUES (gen_random_uuid(), %s, %s, 0.4, 'v1') RETURNING part_id""",
        (rec["project"], owner["user"]))
    _one(db, """
        INSERT INTO public.user_acoustic_baseline (user_id, features, detector_version)
        VALUES (%s, '{"f0_mean": {"mean": 4.1, "sd": 1.0, "n": 9}}'::jsonb, 'v1')
        RETURNING id""", (owner["user"],))


def _logs(db, *, days: float) -> dict:
    """One row in each of the four logs, and one in the founder's bug list
    (never the clean-up's, N50 C4 B), `days` old at AS_OF."""
    at = _at(days)
    owner = _person(db, "account", created=days + 1)
    project = _project(db, owner, touched=days)
    take = _one(db, """
        INSERT INTO public.v2_sessions (id, user_id, owner_principal_id,
            project_id, arc_id, take_index)
        VALUES (gen_random_uuid(), %s, %s, %s, %s, 1) RETURNING id""",
        (owner["user"], owner["principal"], project, project))
    rows = {
        "processing_jobs": _one(db, """
            INSERT INTO public.processing_jobs (id, kind, created_at, updated_at,
                                                enqueued_at)
            VALUES (gen_random_uuid(), 'session_recording', %s, %s, %s)
            RETURNING id""", (at, at, at)),
        "dev_bugs": _one(db, """
            INSERT INTO public.dev_bugs (text, created_at) VALUES ('old bug', %s)
            RETURNING id""", (at,)),
        "life_reminder_log": _one(db, """
            INSERT INTO public.life_reminder_log (user_id, slot, sent_on, created_at)
            VALUES (gen_random_uuid(), 'morning', %s::date, %s) RETURNING id""",
            (at, at)),
        "admin_annotations_log": _one(db, """
            INSERT INTO public.admin_annotations_log (user_id, session_id, created_at)
            VALUES (%s, %s, %s) RETURNING id""", (owner["user"], take, at)),
    }
    rows["mlc3_service_backpressure_events"] = _backpressure(db, at)
    return {table: str(row) for table, row in rows.items()}


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def _financial(db) -> dict:
    """Rule 4 at AS_OF (1 June 2001): a row made in 1995 or before is due,
    its financial year having ended five years ago. The year is Warsaw's:
    the cut is 1 January 1996 00:00 there, 31 December 1995 23:00 UTC."""
    payer = _person(db, "account", created=3000)
    erasing = _person(db, "account", created=3000)
    pausing = _person(db, "account", created=3000)

    def ledger(owner: dict, at: datetime) -> str:
        return str(_one(db, """
            INSERT INTO public.token_ledger (user_id, delta, balance_after,
                                             action, ref_id, created_at)
            VALUES (%s, -3000, 0, 'take_short', %s, %s) RETURNING id""",
            (owner["user"], str(uuid.uuid4()), at)))

    def usage(at: datetime) -> str:
        return str(_one(db, """
            INSERT INTO public.llm_usage (surface, model, tokens_in,
                                          tokens_out, created_at)
            VALUES ('whisper_take', 'whisper-1', 10, 20, %s) RETURNING id""",
            (at,)))

    rows = {
        "ledger_1995": ledger(payer, _utc(1995, 3, 10)),
        # 23:30 UTC on 31 December 1995 is already 1996 in Warsaw: not due.
        "ledger_warsaw_1996": ledger(payer, _utc(1995, 12, 31, 23, 30)),
        "ledger_1996": ledger(payer, _utc(1996, 6, 1)),
        # A call with no account, 23:30 on 31 December 1995 in Warsaw: due.
        "usage_1995": usage(_utc(1995, 12, 31, 22, 30)),
        "usage_1996": usage(_utc(1996, 1, 1)),
        # Due by its year, but its account is being erased: left to that.
        "ledger_erasing": ledger(erasing, _utc(1995, 3, 10)),
        # Due: only a project of this account is being deleted (0378).
        "ledger_pausing": ledger(pausing, _utc(1995, 3, 10)),
    }
    _one(db, """
        INSERT INTO public.data_purge_requests (acquisition_principal_id,
            trigger_kind, idempotency_key)
        VALUES (%s, 'account_deletion', %s) RETURNING id""",
        (erasing["principal"], str(uuid.uuid4())))
    _one(db, """
        INSERT INTO public.data_purge_requests (acquisition_principal_id,
            trigger_kind, project_id, idempotency_key)
        VALUES (%s, 'project_deletion', %s, %s) RETURNING id""",
        (pausing["principal"], _project(db, pausing, touched=3000),
         str(uuid.uuid4())))
    return rows


def _backpressure(db, at: datetime) -> str:
    """The backpressure log is append-only and names a rollout revision this
    lane cannot mint: written as replication would, then back to normal."""
    with db.cursor() as cur:
        cur.execute("SET session_replication_role = replica")
        try:
            cur.execute("""
                INSERT INTO public.mlc3_service_backpressure_events (
                    rollout_revision_id, typed_state, counter_snapshot,
                    event_sha256, created_at)
                VALUES (gen_random_uuid(), 'MLC3_ROLLOUT_HALTED', '{}'::jsonb,
                        %s, %s) RETURNING id""", (uuid.uuid4().hex * 2, at))
            return str(cur.fetchone()[0])
        finally:
            cur.execute("SET session_replication_role = DEFAULT")


def _jobs_evidence_points_at(db, *, days: float) -> dict:
    """Two old jobs, one named by a stage run and one by a transition event."""
    at = _at(days)
    owner = _person(db, "account", created=days + 2)
    project = _project(db, owner, touched=days)
    take = str(_one(db, """
        INSERT INTO public.v2_sessions (id, user_id, owner_principal_id,
            project_id, arc_id, take_index)
        VALUES (gen_random_uuid(), %s, %s, %s, %s, 1) RETURNING id""",
        (owner["user"], owner["principal"], project, project)))
    staged, moved = (str(_one(db, """
        INSERT INTO public.processing_jobs (id, kind, created_at, updated_at,
                                            enqueued_at)
        VALUES (gen_random_uuid(), 'session_recording', %s, %s, %s)
        RETURNING id""", (at, at, at))) for _ in range(2))
    _one(db, """
        INSERT INTO public.processing_stage_runs (id, processing_job_id,
            owner_principal_id, project_id, take_id, stage, status,
            attempt_count, input_hash, idempotency_key)
        VALUES (gen_random_uuid(), %s, %s, %s, %s, 'transcription', 'running',
                1, repeat('a', 64), %s) RETURNING id""",
        (staged, owner["principal"], project, take, f"stage-{uuid.uuid4()}"))
    _one(db, """
        INSERT INTO public.recording_attempts (id, owner_principal_id, project_id,
            upload_idempotency_key, recording_kind, status, attempt_count)
        VALUES (%s, %s, %s, %s, 'spoken', 'processing', 1) RETURNING id""",
        (take, owner["principal"], project, f"upload-{uuid.uuid4()}"))
    _one(db, """
        INSERT INTO public.processing_transition_events (recording_attempt_id,
            processing_job_id, owner_principal_id, project_id, to_status, stage,
            attempt_count, input_hash, idempotency_key)
        VALUES (%s, %s, %s, %s, 'processing', 'transcription', 1,
                repeat('b', 64), %s) RETURNING id""",
        (take, moved, owner["principal"], project, f"move-{uuid.uuid4()}"))
    return {"staged": staged, "moved": moved, "take": take}


def _world(db) -> dict:
    """Exactly one thing due per line of EXPECTED, beside its near misses."""
    w: dict = {}
    # Rule 1: a guest 40 days old (due) and one 10 days old (not).
    w["guest_old"] = _person(db, "guest", created=40)
    w["guest_old_rec"] = _recording(
        db, acquirer=w["guest_old"], owner=w["guest_old"], made=39,
        project=_project(db, w["guest_old"], touched=39))
    w["guest_new"] = _person(db, "guest", created=10)
    w["guest_new_rec"] = _recording(
        db, acquirer=w["guest_new"], owner=w["guest_new"], made=9,
        project=_project(db, w["guest_new"], touched=9))
    # A guest an account claimed: never rule 1, and its recording counts
    # under the account, which changed a project 20 days ago (N46).
    w["claimer"] = _person(db, "account", created=500)
    _project(db, w["claimer"], touched=20)
    w["claimed"] = _person(db, "claimed_guest", created=400, claimed_by=w["claimer"])
    w["claimed_rec"] = _recording(
        db, acquirer=w["claimed"], owner=w["claimer"], made=400,
        project=_project(db, w["claimer"], touched=400))
    # Rule 2: an idle account (due) and a busy one, whose other project
    # changed 30 days ago (not), both with measurements.
    w["idle"] = _person(db, "account", created=500)
    w["idle_rec"] = _recording(db, acquirer=w["idle"], owner=w["idle"], made=400,
                               project=_project(db, w["idle"], touched=400))
    _measurements(db, w["idle_rec"])
    w["busy"] = _person(db, "account", created=500)
    w["busy_rec"] = _recording(db, acquirer=w["busy"], owner=w["busy"], made=400,
                               project=_project(db, w["busy"], touched=400))
    _project(db, w["busy"], touched=30)
    _measurements(db, w["busy_rec"])
    # Rule 3: each log 100 days old (due) and 80 days old (not), and two old
    # jobs that deletion evidence points at (kept).
    w["old_logs"] = _logs(db, days=100)
    w["new_logs"] = _logs(db, days=80)
    w["kept_jobs"] = _jobs_evidence_points_at(db, days=100)
    # Rule 4: three rows due, four near misses (financial years).
    w["financial"] = _financial(db)
    return w


def _report(db, as_of: str = AS_OF) -> dict:
    return {(r["rule"], r["would_delete"]): r["how_many"] for r in _rows(
        db, "SELECT * FROM public.retention_report_v1(%s)", (as_of,))}


def _lines(lines) -> dict:
    return {(line["rule"], line["would_delete"]): line["how_many"] for line in lines}


def _measurements_left(db, rec: dict) -> dict:
    return _rows(db, """
        SELECT
          (SELECT count(*) FROM public.snippets
            WHERE session_id = %(t)s AND metrics IS NOT NULL) AS snippets,
          (SELECT count(*) FROM public.snippets
            WHERE session_id = %(t)s AND transcript IS NOT NULL) AS words,
          (SELECT count(*) FROM public.candidate_windows
            WHERE session_id = %(t)s AND metrics IS NOT NULL) AS windows,
          (SELECT count(*) FROM public.v2_sessions WHERE id = %(t)s
              AND num_nonnulls(global_wpm, global_pause_ms, global_dynamic_db,
                               global_pitch_center, global_energy, kpi_score) > 0)
             AS take_measures,
          (SELECT count(*) FROM public.session_sniper_metrics
            WHERE session_id = %(t)s) AS sniper,
          (SELECT count(*) FROM public.dimension_evaluations
            WHERE session_id = %(t)s::text) AS dimensions,
          (SELECT count(*) FROM public.acoustic_feature_snapshots a
             JOIN public.evidence_spans e ON e.id = a.evidence_span_id
            WHERE e.take_id = %(t)s AND a.features <> '{}'::jsonb) AS snapshots,
          (SELECT count(*) FROM public.arc_part_acoustics
            WHERE user_id = %(u)s) AS parts,
          (SELECT count(*) FROM public.user_acoustic_baseline
            WHERE user_id = %(u)s) AS baselines""",
        {"t": rec["take"], "u": rec["owner"]["user"]})[0]


def _deletion(db, audio: str) -> dict | None:
    rows = _rows(db, """
        SELECT purge_request_id, retention_run_id
          FROM public.processing_audio_object_deletion_events
         WHERE audio_object_id = %s""", (audio,))
    return rows[0] if rows else None


# ── The cases ───────────────────────────────────────────────────────────────

class TestOneDefinitionOfWhatIsDue:

    def test_the_report_the_script_and_a_dry_run_count_exactly_the_due_rows(
            self, db, storage):
        w = _world(db)
        report = _report(db)
        assert report == EXPECTED

        # The founder's script is that report: run it at the same moment.
        script = (ROOT / "scripts" / "retention_report.sql").read_text()
        code = "\n".join(line.split("--", 1)[0] for line in script.splitlines())
        assert code.count("now()") == 1
        assert {(r["rule"], r["would_delete"]): r["how_many"] for r in _rows(
            db, code.replace("now()", "%s::timestamptz"), (AS_OF,))} == report

        summary = rc.run(_Database(db), as_of=AS_OF)
        assert (summary["mode"], summary["state"], summary["refusal"]) == (
            "dry_run", "completed", None)
        assert _lines(summary["due"]) == report
        stored = _rows(db, "SELECT * FROM public.retention_cleaner_runs WHERE id = %s",
                       (summary["run_id"],))[0]
        assert stored["finished_at"] is not None and stored["done"] == {}

        # A dry run deletes nothing.
        assert storage["deleted"] == []
        assert _deletion(db, w["idle_rec"]["audio"]) is None
        assert _measurements_left(db, w["idle_rec"])["snippets"] == 2
        assert _one(db, "SELECT count(*) FROM public.dev_bugs WHERE id = %s",
                    (int(w["old_logs"]["dev_bugs"]),)) == 1
        assert _present(db, "token_ledger", w["financial"]["ledger_1995"])
        assert _present(db, "llm_usage", w["financial"]["usage_1995"])
        assert _one(db, """
            SELECT count(*) FROM public.data_purge_requests
             WHERE acquisition_principal_id = %s""",
            (w["guest_old"]["principal"],)) == 0

    def test_its_numbers_are_the_founders_report_of_5_october_but_three(self, db):
        """0423 kept every rule of the report the founder ran (N47) and
        refined one line: a job deletion evidence points at is kept, and
        counted apart (N50 C3 A). 0426 took dev_bugs off it (C4 B) and added
        rule 4 (P7). Here, the only places they differ."""
        _world(db)
        original = {(r["rule"], r["would_delete"]): r["how_many"]
                    for r in _rows(db, REPORT_2026_10_05, {"as_of": AS_OF})}
        report = _report(db)
        assert original.pop((3, LOGS + "dev_bugs")) == 1
        assert (3, LOGS + "dev_bugs") not in report
        for line, count in original.items():
            if line == (3, LOGS + "processing_jobs"):
                assert count == report[line] + report[(3, KEPT + "processing_jobs")]
            else:
                assert report[line] == count, line
        assert {line for line in report if line[0] == 4} == {
            (4, FIN + "llm_usage"), (4, FIN + "token_ledger")}

    def test_a_job_evidence_points_at_cannot_go_without_rewriting_that_evidence(
            self, db):
        """Why the refinement exists: the transition event's FK sets the job
        to NULL, and the append-only evidence refuses."""
        w = _world(db)
        with db.cursor() as cur:
            cur.execute("SAVEPOINT attempt")
            cur.execute("SET ROLE service_role")
            with pytest.raises(psycopg2.Error, match="append-only"):
                cur.execute("DELETE FROM public.processing_jobs WHERE id = %s",
                            (w["kept_jobs"]["moved"],))
            cur.execute("ROLLBACK TO SAVEPOINT attempt")
            cur.execute("RESET ROLE")

    def test_an_erasure_under_way_keeps_the_cleaner_out(self, db):
        w = _world(db)
        _one(db, """
            INSERT INTO public.data_purge_requests (acquisition_principal_id,
                trigger_kind, idempotency_key)
            VALUES (%s, 'account_deletion', %s) RETURNING id""",
            (w["idle"]["principal"], str(uuid.uuid4())))
        report = _report(db)
        assert report[(2, "audio files not used for 12 months")] == 0
        assert report[(2, MEASURES + "snippets.metrics")] == 0


class TestTheTwoKeys:

    def test_a_live_request_is_refused_while_the_key_is_off(self, db, storage,
                                                            monkeypatch):
        monkeypatch.setattr(rc, "RETENTION_CLEANER_LIVE", False)
        w = _world(db)
        summary = rc.run(_Database(db), mode="live", as_of=AS_OF)
        assert (summary["requested_mode"], summary["mode"], summary["state"],
                summary["refusal"]) == ("live", "dry_run", "refused",
                                        rc.REFUSAL_LIVE_OFF)
        assert _lines(summary["due"]) == EXPECTED
        assert storage["deleted"] == []
        assert _deletion(db, w["idle_rec"]["audio"]) is None
        assert _one(db, "SELECT count(*) FROM public.retention_cleaner_runs "
                        "WHERE mode = 'live'") == 0

    def test_the_database_will_not_look_ahead(self, db):
        with db.cursor() as cur:
            cur.execute("SAVEPOINT ahead")
            with pytest.raises(psycopg2.Error, match="RETENTION_AS_OF_IN_THE_FUTURE"):
                cur.execute("SELECT public.begin_retention_live_run_v1('x', now() + interval '1 day')")
            cur.execute("ROLLBACK TO SAVEPOINT ahead")


class TestALiveRun:

    def test_it_deletes_exactly_what_was_due_and_nothing_retained(
            self, db, storage, key_on):
        w = _world(db)
        retained_before = _retained(db)
        summary = rc.run(_Database(db), mode="live", as_of=AS_OF,
                         purge_execution=True)
        assert (summary["mode"], summary["state"]) == ("live", "completed"), summary

        # Rule 1: the account purge erased the old guest, recording and all.
        request = _rows(db, """
            SELECT trigger_kind, state FROM public.data_purge_requests
             WHERE acquisition_principal_id = %s""", (w["guest_old"]["principal"],))
        assert request == [{"trigger_kind": "retention_expiry", "state": "done"}]
        assert _deletion(db, w["guest_old_rec"]["audio"])["purge_request_id"]

        # Rule 2: the idle account's recording, its event naming this run,
        # and every measurement it had; the words stay.
        event = _deletion(db, w["idle_rec"]["audio"])
        assert event["purge_request_id"] is None
        assert str(event["retention_run_id"]) == summary["run_id"]
        assert _measurements_left(db, w["idle_rec"]) == {
            "snippets": 0, "words": 2, "windows": 0, "take_measures": 0,
            "sniper": 0, "dimensions": 0, "snapshots": 0, "parts": 0,
            "baselines": 0}
        assert _one(db, """
            SELECT global_fillers FROM public.v2_sessions WHERE id = %s""",
            (w["idle_rec"]["take"],)) == 3, "a word count is not a voice measure"
        claim = _rows(db, """
            SELECT outcome FROM public.retention_cleaner_audio_claims
             WHERE run_id = %s""", (summary["run_id"],))
        assert claim == [{"outcome": "deleted"}]

        # Exactly two objects left storage: the guest's and the idle one's.
        assert sorted(storage["deleted"]) == sorted(
            [w["guest_old_rec"]["key"], w["idle_rec"]["key"]])

        # Rule 3: the old rows of the four logs, no other; never the
        # founder's bug list (N50 C4 B).
        for table, row in w["old_logs"].items():
            assert _present(db, table, row) is (table == "dev_bugs"), table
        for table, row in w["new_logs"].items():
            assert _present(db, table, row) is True, table

        # Rule 4: the financial records whose years have ended, no other.
        fin = w["financial"]
        for name, table in (("ledger_1995", "token_ledger"),
                            ("ledger_pausing", "token_ledger"),
                            ("usage_1995", "llm_usage")):
            assert _present(db, table, fin[name]) is False, name
        for name, table in (("ledger_warsaw_1996", "token_ledger"),
                            ("ledger_1996", "token_ledger"),
                            ("ledger_erasing", "token_ledger"),
                            ("usage_1996", "llm_usage")):
            assert _present(db, table, fin[name]) is True, name
        for job in ("staged", "moved"):
            assert _present(db, "processing_jobs", w["kept_jobs"][job]) is True
        assert str(_one(db, """
            SELECT processing_job_id FROM public.processing_stage_runs
             WHERE take_id = %s""", (w["kept_jobs"]["take"],))) == w["kept_jobs"]["staged"]

        # Nothing that was not due.
        for name in ("guest_new_rec", "claimed_rec", "busy_rec"):
            assert _deletion(db, w[name]["audio"]) is None, name
        assert _measurements_left(db, w["busy_rec"])["snippets"] == 2
        assert _measurements_left(db, w["busy_rec"])["baselines"] == 1
        for name in ("guest_new", "claimed"):
            assert _one(db, """
                SELECT count(*) FROM public.data_purge_requests
                 WHERE acquisition_principal_id = %s""", (w[name]["principal"],)) == 0

        # Nothing retained: every evidence row is still there.
        assert _retained(db) == retained_before

        # The record: what it set out to do, what it did, what is left.
        assert _lines(summary["due"]) == EXPECTED
        left = _lines(summary["left_due"])
        assert left.pop((3, KEPT + "processing_jobs")) == 2
        assert set(left.values()) == {0}
        done = summary["done"]
        assert done["guests.erased"] == 1 and done["audio.deleted"] == 1
        assert done["measurements.snippets_metrics"] == 2
        assert done["measurements.dimension_evaluations"] == 2
        assert done["measurements.user_acoustic_baseline"] == 1
        for table in rc.LOG_TABLES:
            assert done[f"logs.{table}"] == 1, table
        assert done["financial.token_ledger"] == 2
        assert done["financial.llm_usage"] == 1
        assert "logs.dev_bugs" not in done

    def test_a_second_run_finds_nothing_left_to_do(self, db, storage, key_on):
        w = _world(db)
        rc.run(_Database(db), mode="live", as_of=AS_OF,
               purge_execution=True)
        events = _one(db, "SELECT count(*) FROM public.processing_audio_object_deletion_events")
        requests = _one(db, "SELECT count(*) FROM public.data_purge_requests")
        storage["deleted"].clear()

        again = rc.run(_Database(db), mode="live", as_of=AS_OF,
                       purge_execution=True)
        assert again["state"] == "completed"
        due = _lines(again["due"])
        assert due.pop((3, KEPT + "processing_jobs")) == 2
        assert set(due.values()) == {0}
        assert again["done"] == {}
        assert storage["deleted"] == []
        assert _one(db, "SELECT count(*) FROM public.processing_audio_object_deletion_events") == events
        assert _one(db, "SELECT count(*) FROM public.data_purge_requests") == requests
        assert _deletion(db, w["busy_rec"]["audio"]) is None

    def test_a_recording_whose_object_will_not_go_outlives_its_measurements_never_the_reverse(
            self, db, storage, key_on):
        w = _world(db)
        storage["refuse"].add(w["idle_rec"]["key"])
        first = rc.run(_Database(db), mode="live", as_of=AS_OF,
                       purge_execution=True)
        assert first["done"]["audio.failed"] == 1
        assert _deletion(db, w["idle_rec"]["audio"]) is None, "the object is still there"
        left = _measurements_left(db, w["idle_rec"])
        assert left["snippets"] == left["snapshots"] == left["sniper"] == 0
        assert _rows(db, """
            SELECT outcome, error_code FROM public.retention_cleaner_audio_claims
             WHERE run_id = %s""", (first["run_id"],)) == [
            {"outcome": "failed", "error_code": "ValueError"}]

        # The next run finds the recording again and finishes it.
        storage["refuse"].clear()
        second = rc.run(_Database(db), mode="live", as_of=AS_OF,
                        purge_execution=True)
        assert second["done"]["audio.deleted"] == 1
        assert str(_deletion(db, w["idle_rec"]["audio"])["retention_run_id"]) == (
            second["run_id"])

    def test_a_guest_whose_other_erasure_is_open_is_left_to_it(
            self, db, storage, key_on):
        """Still counted (it is not erased yet), never erased twice."""
        w = _world(db)
        other = _one(db, """
            INSERT INTO public.data_purge_requests (acquisition_principal_id,
                trigger_kind, idempotency_key)
            VALUES (%s, 'lawful_deletion', %s) RETURNING id""",
            (w["guest_old"]["principal"], str(uuid.uuid4())))
        summary = rc.run(_Database(db), mode="live", as_of=AS_OF,
                         purge_execution=True)
        assert _lines(summary["due"])[(1, "unclaimed guests older than 30 days")] == 1
        assert summary["done"]["guests.skipped_another_erasure_open"] == 1
        assert _rows(db, """
            SELECT id FROM public.data_purge_requests
             WHERE acquisition_principal_id = %s""",
            (w["guest_old"]["principal"],)) == [{"id": other}]
        assert w["guest_old_rec"]["key"] not in storage["deleted"]

    def test_a_guest_whose_erasure_stopped_for_review_is_left_for_a_person(
            self, db, storage, key_on):
        """Its own erasure stopped on rows no rule decides: no run opens
        another or runs it again, and the guest is still counted as due."""
        w = _world(db)
        guest = w["guest_old"]["principal"]
        stopped = _one(db, """
            INSERT INTO public.data_purge_requests (acquisition_principal_id,
                trigger_kind, idempotency_key, state)
            VALUES (%s, 'retention_expiry',
                    'retention-cleaner:unclaimed-guest-30-days:' || %s::text,
                    'review_required') RETURNING id""", (guest, guest))
        summary = rc.run(_Database(db), mode="live", as_of=AS_OF,
                         purge_execution=True)
        assert summary["done"]["guests.skipped_left_for_a_person"] == 1
        assert "guests.erased" not in summary["done"]
        assert _rows(db, """
            SELECT id, state FROM public.data_purge_requests
             WHERE acquisition_principal_id = %s""", (guest,)) == [
            {"id": stopped, "state": "review_required"}]
        assert w["guest_old_rec"]["key"] not in storage["deleted"]
        assert _lines(summary["left_due"])[
            (1, "unclaimed guests older than 30 days")] == 1

    def test_without_the_purge_switch_no_guest_is_erased_and_the_rest_goes(
            self, db, storage, key_on):
        """Rule 1 is a purge and obeys PHASE1_PURGE_EXECUTION_ENABLED; rules 2
        and 3 are not purges."""
        w = _world(db)
        summary = rc.run(_Database(db), mode="live", as_of=AS_OF)
        assert (summary["mode"], summary["state"]) == ("live", "completed")
        assert summary["done"]["guests.held_purge_execution_off"] == 1
        assert _one(db, """
            SELECT count(*) FROM public.data_purge_requests
             WHERE acquisition_principal_id = %s""",
            (w["guest_old"]["principal"],)) == 0
        assert _deletion(db, w["guest_old_rec"]["audio"]) is None
        assert w["guest_old_rec"]["key"] not in storage["deleted"]
        assert _lines(summary["left_due"])[
            (1, "unclaimed guests older than 30 days")] == 1
        assert summary["done"]["audio.deleted"] == 1
        assert str(_deletion(db, w["idle_rec"]["audio"])["retention_run_id"]) == (
            summary["run_id"])
        for table in rc.LOG_TABLES:
            assert summary["done"][f"logs.{table}"] == 1, table

    def test_an_object_already_gone_is_recorded_as_such(self, db, storage, key_on):
        w = _world(db)
        storage["refuse"].add(w["idle_rec"]["key"])
        storage["absent"] = True
        summary = rc.run(_Database(db), mode="live", as_of=AS_OF,
                         purge_execution=True)
        assert summary["done"]["audio.already_absent"] == 1
        assert _deletion(db, w["idle_rec"]["audio"])["retention_run_id"]


class TestTheGuardsOpenForALiveRunOnly:

    def test_a_voice_snapshot_still_refuses_any_other_change(self, db):
        w = _world(db)
        statement = """
            UPDATE public.acoustic_feature_snapshots a SET features = '{}'::jsonb
              FROM public.evidence_spans e
             WHERE e.id = a.evidence_span_id AND e.take_id = %s"""
        with db.cursor() as cur:
            for setting in (None, "run"):
                cur.execute("SAVEPOINT wipe")
                if setting:
                    cur.execute("SELECT set_config('willab.retention_run_id', %s, true),"
                                "       set_config('willab.retention_audio_object_id', %s, true)",
                                (str(uuid.uuid4()), w["idle_rec"]["audio"]))
                with pytest.raises(psycopg2.Error, match="append-only"):
                    cur.execute(statement, (w["idle_rec"]["take"],))
                cur.execute("ROLLBACK TO SAVEPOINT wipe")

    def test_a_backpressure_event_goes_only_when_it_is_older_than_90_days(self, db):
        """The trigger reads the real clock: a row is old or young today."""
        old = _backpressure(db, datetime.now(timezone.utc) - timedelta(days=100))
        young = _backpressure(db, datetime.now(timezone.utc) - timedelta(days=10))
        with db.cursor() as cur:
            cur.execute("SAVEPOINT young")
            cur.execute("SET ROLE service_role")
            with pytest.raises(psycopg2.Error, match="MLC3_GENERAL_SERVICE_APPEND_ONLY"):
                cur.execute("DELETE FROM public.mlc3_service_backpressure_events "
                            "WHERE id = %s", (young,))
            cur.execute("ROLLBACK TO SAVEPOINT young")
            cur.execute("SET ROLE service_role")
            cur.execute("DELETE FROM public.mlc3_service_backpressure_events "
                        "WHERE id = %s", (old,))
            cur.execute("RESET ROLE")
        assert _present(db, "mlc3_service_backpressure_events", old) is False
        assert _present(db, "mlc3_service_backpressure_events", young) is True

    def test_a_deletion_event_names_exactly_one_act(self, db):
        w = _world(db)
        audio = w["busy_rec"]["audio"]
        with db.cursor() as cur:
            cur.execute("SAVEPOINT orphan_event")
            with pytest.raises(psycopg2.Error, match="one_act"):
                cur.execute("""
                    INSERT INTO public.processing_audio_object_deletion_events (
                        audio_object_id, acquisition_principal_id,
                        storage_provider, bucket, object_key,
                        exact_bytes_sha256, evidence_sha256)
                    SELECT id, acquisition_principal_id, storage_provider, bucket,
                           object_key, exact_bytes_sha256, repeat('e', 64)
                      FROM public.processing_audio_objects WHERE id = %s""", (audio,))
            cur.execute("ROLLBACK TO SAVEPOINT orphan_event")

    def test_a_finished_run_record_is_final(self, db):
        run_id = _one(db, "SELECT (public.record_retention_dry_run_v1('dry_run', 'x'))->>'id'")
        with db.cursor() as cur:
            for statement in (
                    "UPDATE public.retention_cleaner_runs SET state = 'failed' WHERE id = %s",
                    "DELETE FROM public.retention_cleaner_runs WHERE id = %s"):
                cur.execute("SAVEPOINT final")
                with pytest.raises(psycopg2.Error, match="RETENTION_RUN_RECORD"):
                    cur.execute(statement, (run_id,))
                cur.execute("ROLLBACK TO SAVEPOINT final")


class TestTheWave3SignOff:
    """N50: the founder's bug list is not a log (C4 B); the financial
    records go when their five years end, behind the same key (P7)."""

    def _live_run(self, db) -> str:
        return str(_one(db, "SELECT public.begin_retention_live_run_v1('x', %s)->>'id'",
                        (AS_OF,)))

    def test_a_live_run_cannot_even_list_the_bug_list(self, db):
        run = self._live_run(db)
        with db.cursor() as cur:
            for rule, relation in (("logs", "dev_bugs"), ("financial", "dev_bugs"),
                                   ("financial", "v2_student_details")):
                cur.execute("SAVEPOINT listing")
                with pytest.raises(psycopg2.Error, match="RETENTION_RULE_UNKNOWN"):
                    cur.execute("SELECT * FROM public.list_retention_due_v1("
                                "%s, %s, %s, 10)", (run, rule, relation))
                cur.execute("ROLLBACK TO SAVEPOINT listing")

    def test_a_financial_year_ends_at_midnight_in_warsaw(self, db):
        """A row made in 2026 is due from 1 January 2032, 00:00 in Warsaw:
        23:00 UTC on 31 December 2031, an hour before UTC's new year."""
        made_2026 = _utc(2026, 3, 10)

        def due(as_of: datetime) -> bool:
            return bool(_one(db, "SELECT %s < public.retention_financial_cut_v1(%s)",
                             (made_2026, as_of)))

        assert due(_utc(2031, 12, 31, 22, 59)) is False
        assert due(_utc(2031, 12, 31, 23, 0)) is True
        assert due(_utc(2032, 7, 1)) is True
        # And the last moment of 2026 in Warsaw belongs to 2026.
        assert _one(db, "SELECT %s < public.retention_financial_cut_v1(%s)",
                    (_utc(2026, 12, 31, 22, 59), _utc(2031, 12, 31, 23, 0))) is True
        assert _one(db, "SELECT %s < public.retention_financial_cut_v1(%s)",
                    (_utc(2026, 12, 31, 23, 1), _utc(2031, 12, 31, 23, 0))) is False

    def test_the_door_is_deletes_by_id_and_nothing_more(self, db):
        """What 0426 grants the service role on the two tables: removing a
        row, found by its id. Not a word of what the row says."""
        with db.cursor() as cur:
            for table in ("token_ledger", "llm_usage"):
                cur.execute("""
                    SELECT has_table_privilege('service_role', %(t)s, 'DELETE'),
                           has_table_privilege('service_role', %(t)s, 'INSERT'),
                           has_table_privilege('service_role', %(t)s, 'UPDATE'),
                           has_column_privilege('service_role', %(t)s, 'id', 'SELECT'),
                           has_column_privilege('service_role', %(t)s, 'created_at', 'SELECT'),
                           has_column_privilege('service_role', %(t)s, 'user_id', 'SELECT')
                    """, {"t": f"public.{table}"})
                assert cur.fetchone() == (True, False, False, True, True, False), table


def _present(db, table: str, row_id: str) -> bool:
    return bool(_one(db, sql.SQL("SELECT count(*) FROM public.{} WHERE id::text = %s")
                     .format(sql.Identifier(table)), (str(row_id),)))


def _retained(db) -> dict:
    """Counts of the evidence the clean-up must never touch."""
    return _rows(db, """
        SELECT
          (SELECT count(*) FROM public.owner_principals) AS owners,
          (SELECT count(*) FROM public.owner_claim_events) AS claims,
          (SELECT count(*) FROM public.processing_audio_objects) AS audio_rows,
          (SELECT count(*) FROM public.processing_recording_attempts) AS attempts,
          (SELECT count(*) FROM public.processing_authorization_receipts) AS receipts,
          (SELECT count(*) FROM public.processing_authorization_snapshots) AS snapshots,
          (SELECT count(*) FROM public.processing_stage_runs) AS stage_runs,
          (SELECT count(*) FROM public.processing_transition_events) AS transitions,
          (SELECT count(*) FROM public.evidence_spans) AS spans,
          (SELECT count(*) FROM public.acoustic_feature_snapshots) AS voice_rows""")[0]
