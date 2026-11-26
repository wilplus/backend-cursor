"""
STORY    As a volunteer, I resume my isolated baseline where I left it and
         enter once both recordings and their felt energy are saved.
OUTCOME
  O1  Lost responses, permission refusal and reload preserve the next step;
      each prompt asks felt energy before felt valence and saved audio
      remains privately replayable during both report steps.
  O2  Only granted accounts enter. Each run has separate, owner-only history.
  O3  A held-out prediction receives only admissible audio. The private
      comparison row appears after the exact prediction is stored.
  O4  A stale signed-in session cannot recreate data after account deletion.
PROVES   O1 -> test_entry_resumes_after_a_lost_audio_response
         O2 -> test_entry_resumes_after_a_lost_audio_response
         O3 -> test_prediction_inputs_and_labels_have_separate_boundaries
         O4 -> test_deleted_account_cannot_restart_with_an_old_session
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
import struct
import uuid
import wave
from pathlib import Path
from types import SimpleNamespace

import psycopg2
import pytest
from flask import jsonify
from postgrest.exceptions import APIError
from psycopg2 import sql
from psycopg2.extras import Json, RealDictCursor

DSN = os.environ.get("EXPERIMENT_BASELINE_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(not DSN, reason="disposable baseline pilot rehearsal only")
ROOT = Path(__file__).resolve().parents[1]
API = "/v2/experiments/baseline-pilot"
CONSENT = {"participant": True, "researcher": False, "version": "test-disclosure"}
PROTOCOL = {
    "version": "synthetic-v1",
    "disclosure": {"version": "test-disclosure", "recording": "Test recording",
                   "purpose": "Test purpose", "use": "Test use"},
    "prompts": [
        {"id": "quiet", "prompt": "Synthetic quiet context", "intended_energy": "low"},
        {"id": "energizing", "prompt": "Synthetic energizing context", "intended_energy": "high"},
    ],
}
POLISH_PROTOCOL = {
    **PROTOCOL,
    "version": "synthetic-pl-v1",
    "disclosure": {**PROTOCOL["disclosure"], "recording": "Nagranie testowe"},
    "prompts": [{**prompt, "prompt": f"Polskie pytanie {index}"}
                for index, prompt in enumerate(PROTOCOL["prompts"], start=1)],
}
EVALUATION_PROMPTS = (
    {"id": "a", "prompt": "Synthetic prompt A", "intended_valence": "pleasant",
     "intended_energy": "low", "partition": "calibration"},
    {"id": "b", "prompt": "Synthetic prompt B", "intended_valence": "unpleasant",
     "intended_energy": "high", "partition": "calibration"},
    {"id": "c", "prompt": "Synthetic prompt C", "intended_valence": "pleasant",
     "intended_energy": "high", "partition": "held_out"},
    {"id": "d", "prompt": "Synthetic prompt D", "intended_valence": "unpleasant",
     "intended_energy": "low", "partition": "held_out"},
)
REPORT = {"felt_energy": "medium_to_high"}
PRIVATE_FAILURE_DETAIL = "synthetic private recording and label detail"


def _install_function(cur, migration, name):
    marker = f"CREATE OR REPLACE FUNCTION public.{name}("
    source = (ROOT / "migrations" / migration).read_text()
    cur.execute(marker + source.split(marker, 1)[1].split("$$;", 1)[0] + "$$;")


@pytest.fixture(scope="module")
def connection():
    parameters = psycopg2.extensions.parse_dsn(DSN)
    host = Path(parameters.get("host", "/invalid"))
    if not (parameters.get("dbname", "").startswith("willab_experiment_baseline_")
            and host.name.startswith("willab-") and host.parent in (Path("/tmp"), Path("/private/tmp"))):
        raise RuntimeError("Refusing a non-disposable database")
    db = psycopg2.connect(DSN)
    db.autocommit = True
    try:
        with db.cursor() as cur:
            cur.execute("""
                DO $$ BEGIN
                    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='anon') THEN
                        CREATE ROLE anon NOLOGIN;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN
                        CREATE ROLE authenticated NOLOGIN;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN
                        CREATE ROLE service_role NOLOGIN BYPASSRLS;
                    END IF;
                END $$;
                ALTER ROLE service_role BYPASSRLS;
                CREATE SCHEMA IF NOT EXISTS auth;
                CREATE TABLE IF NOT EXISTS auth.users(id uuid PRIMARY KEY, deleted_at timestamptz);
                CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql AS 'SELECT NULL::uuid';
                CREATE SCHEMA IF NOT EXISTS storage;
                CREATE TABLE IF NOT EXISTS storage.buckets(id text PRIMARY KEY, name text, public boolean);
                CREATE TABLE IF NOT EXISTS public.owner_principals (
                    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid UNIQUE
                );
                CREATE TABLE IF NOT EXISTS public.owner_claim_events (
                    id uuid PRIMARY KEY, source_owner_principal_id uuid, target_owner_principal_id uuid,
                    claimed_user_id uuid, claimed_at timestamptz
                );
                CREATE TABLE IF NOT EXISTS public.processing_authorization_receipts (acquisition_principal_id uuid);
                CREATE TABLE IF NOT EXISTS public.processing_recording_attempts (acquisition_principal_id uuid);
                CREATE TABLE IF NOT EXISTS public.account_deletion_requests (acquisition_principal_id uuid, state text);
                CREATE TABLE IF NOT EXISTS public.data_purge_requests (acquisition_principal_id uuid, project_id uuid);
            """)
            _install_function(cur, "an_acceptance_alone_never_displaces_the_account.sql", "resolve_phase1_acquisition_principal_v1")
            _install_function(cur, "a_chat_turn_keeps_its_artifact.sql", "owner_chat_linked_principals_v1")
            _install_function(cur, "a_chat_turn_keeps_its_artifact.sql", "owner_chat_may_write_v1")
            for migration in ("a_volunteer_keeps_their_experiments.sql",
                              "a_volunteer_keeps_their_baseline_pilot_answers.sql"):
                ddl = (ROOT / "migrations" / migration).read_text()
                cur.execute(ddl)
                cur.execute(ddl)
        yield db
    finally:
        db.close()


class _PgClient:
    """Translate the pilot's PostgREST calls to SQL on the rehearsal database."""

    def __init__(self, connection):
        self.connection = connection
        self.lose_audio_response = False

    def table(self, name):
        return _PgQuery(self, name)

    def rpc(self, name, params):
        arguments = sql.SQL(", ").join(sql.SQL("{} => %s").format(sql.Identifier(k)) for k in params)
        fn = sql.SQL("public.{}({})").format(sql.Identifier(name), arguments)
        values = [Json(value) if isinstance(value, (dict, list)) else value for value in params.values()]

        def execute():
            many = name == "blind_experiment_baseline_audio"
            statement = sql.SQL("SELECT * FROM {}") if many else sql.SQL("SELECT {} AS value")
            rows = self.execute(statement.format(fn), values)
            if name == "save_experiment_baseline_step" and "p_audio" in params and self.lose_audio_response:
                self.lose_audio_response = False
                raise ConnectionError(PRIVATE_FAILURE_DETAIL)
            return SimpleNamespace(data=rows if many else rows[0]["value"])

        return SimpleNamespace(execute=execute)

    def execute(self, statement, values):
        try:
            with self.connection.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql.SQL("WITH response AS ({}) SELECT to_jsonb(response) AS value FROM response")
                            .format(statement), values)
                return [row["value"] for row in cur.fetchall()]
        except psycopg2.Error as exc:
            raise APIError({"code": exc.pgcode, "message": exc.diag.message_primary}) from exc


class _PgQuery:
    def __init__(self, client, name):
        self.client, self.relation = client, sql.Identifier(name)
        self.columns = sql.SQL("*")
        self.filters = {}
        self.sort = []
        self.bounds = None
        self.payload = None
        self.dedupe = False
        self.deleting = False

    def select(self, columns):
        if columns != "*":
            self.columns = sql.SQL(", ").join(sql.Identifier(key) for key in columns.split(","))
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def order(self, key, *, desc):
        assert desc
        self.sort.append(sql.SQL("{} DESC").format(sql.Identifier(key)))
        return self

    def limit(self, count):
        self.bounds = count, 0
        return self

    def range(self, first, last):
        self.bounds = last - first + 1, first
        return self

    def insert(self, payload):
        self.payload = payload
        return self

    def delete(self, *, returning):
        assert returning == "minimal"
        self.deleting = True
        return self

    def upsert(self, payload, *, on_conflict, ignore_duplicates):
        assert on_conflict == "step_id,model_version" and ignore_duplicates
        self.dedupe = True
        return self.insert(payload)

    def execute(self):
        if self.payload is not None:
            cols = sql.SQL(", ").join(sql.Identifier(key) for key in self.payload)
            arguments = sql.SQL(", ").join(
                sql.SQL("%s::uuid[]") if key == "calibration_step_ids" else sql.SQL("%s")
                for key in self.payload)
            statement = sql.SQL("INSERT INTO public.{} ({}) VALUES ({})").format(self.relation, cols, arguments)
            if self.dedupe:
                statement += sql.SQL(" ON CONFLICT DO NOTHING")
            statement += sql.SQL(" RETURNING *")
            return SimpleNamespace(data=self.client.execute(statement, list(self.payload.values())))
        clause = sql.SQL(" AND ").join(sql.SQL("{} = %s").format(sql.Identifier(key)) for key in self.filters)
        values = list(self.filters.values())
        if self.deleting:
            self.client.execute(sql.SQL("DELETE FROM public.{} WHERE {} RETURNING 1").format(self.relation, clause),
                                values)
            return SimpleNamespace(data=[])
        statement = sql.SQL("SELECT {} FROM public.{} WHERE {}").format(self.columns, self.relation, clause)
        if self.sort:
            statement += sql.SQL(" ORDER BY ") + sql.SQL(", ").join(self.sort)
        if self.bounds:
            statement += sql.SQL(" LIMIT %s OFFSET %s")
            values += list(self.bounds)
        return SimpleNamespace(data=self.client.execute(statement, values))


@pytest.fixture
def pilot_app(connection, monkeypatch):
    import auth
    from app import app
    from config import Config
    from routes.v2 import experiment_baseline as routes
    from services.db import db

    identities = tuple(str(uuid.uuid4()) for _ in range(2))
    with connection.cursor() as cur:
        cur.execute("RESET ROLE")
        cur.executemany("INSERT INTO auth.users(id) VALUES (%s)", [(uid,) for uid in identities])
        cur.executemany("INSERT INTO public.owner_principals(user_id) VALUES (%s)", [(uid,) for uid in identities])
        cur.execute("SET ROLE service_role")
    monkeypatch.setattr(db, "client", _PgClient(connection))
    monkeypatch.setattr(Config, "EXPERIMENT_BASELINE_PILOT_ENABLED", True)
    monkeypatch.setattr(Config, "EXPERIMENT_BASELINE_PILOT_USER_IDS", frozenset(identities))
    monkeypatch.setattr(Config, "EXPERIMENT_BASELINE_PILOT_PROTOCOL", json.dumps({"en": PROTOCOL, "pl": POLISH_PROTOCOL}))
    monkeypatch.setattr(auth, "verify_supabase_token", lambda token: {"sub": token})
    monkeypatch.setenv("INVITE_ONLY_SINCE", "off")
    monkeypatch.setenv("PLF1_PROCESSING_AUTHORIZATION_MODE", "off")
    monkeypatch.setattr(routes, "_recording_refused", lambda: None)
    return app.test_client(), db, identities


def _headers(owner):
    return {"Authorization": f"Bearer {owner}"}


def _start(client, owner, mode="initial", request_id=None, consent=CONSENT, language="en"):
    return client.post(API + "/runs", headers=_headers(owner),
                       json={"mode": mode, "request_id": request_id or str(uuid.uuid4()), "consent": consent,
                             "language": language})


def _state(client, owner):
    result = client.get(API, headers=_headers(owner))
    assert result.status_code == 200 and result.headers["Cache-Control"] == "private, no-store"
    return result.get_json()


def _wave(frequency):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", ""))
        samples = [int(2800 * math.sin(2 * math.pi * frequency * i / 16000)) for i in range(4800)]
        wav.writeframes(struct.pack("<4800h", *samples))
    return buffer.getvalue()


def _step_url(run, name, step_id=None):
    return f"{API}/runs/{run['id']}/steps/{step_id or run['next_step']['id']}/{name}"


def _save_audio(client, owner, run, audio, step_id=None):
    return client.put(_step_url(run, "audio", step_id), headers=_headers(owner),
                      data={"audio": (io.BytesIO(audio), "answer.wav")})


def _save_report(client, owner, run, report=REPORT, step_id=None):
    return client.put(_step_url(run, "report", step_id), headers=_headers(owner), json=report)


def test_entry_resumes_after_a_lost_audio_response(pilot_app, monkeypatch, caplog):
    import sentry_sdk
    from routes.v2 import experiment_baseline as routes

    client, database, (owner, other) = pilot_app
    from config import Config

    with monkeypatch.context() as m:
        m.setattr(Config, "EXPERIMENT_BASELINE_PILOT_ENABLED", False)
        assert client.get(API, headers=_headers(owner)).status_code == 404
    with monkeypatch.context() as m:
        m.setattr(Config, "EXPERIMENT_BASELINE_PILOT_USER_IDS", frozenset({owner}))
        assert client.get(API, headers=_headers(other)).status_code == 404
        assert _start(client, other).status_code == 404
    assert client.get(API).status_code == 401
    assert _state(client, owner)["runs"] == dict.fromkeys(("initial", "on_demand", "refresh"))
    assert _start(client, owner, "on_demand").get_json()["code"] == "PILOT_INITIAL_REQUIRED"
    assert _start(client, owner, consent={**CONSENT, "version": "stale"}).status_code == 422
    with monkeypatch.context() as m:
        extra_prompt = {"id": "later", "prompt": "Synthetic later context", "intended_energy": "high"}
        m.setattr(Config, "EXPERIMENT_BASELINE_PILOT_PROTOCOL",
                  json.dumps({**PROTOCOL, "prompts": [*PROTOCOL["prompts"], extra_prompt]}))
        assert _start(client, owner).get_json()["code"] == "PILOT_PROTOCOL_UNAVAILABLE"
    key = str(uuid.uuid4())
    run = _start(client, owner, request_id=key).get_json()["run"]
    first = run["next_step"]
    assert first["prompt"] == PROTOCOL["prompts"][0]["prompt"]
    polish = client.get(API + "?language=pl", headers=_headers(other)).get_json()
    assert polish["disclosure"] == POLISH_PROTOCOL["disclosure"]
    assert _start(client, other, language="pl").get_json()["run"]["next_step"]["prompt"] == POLISH_PROTOCOL["prompts"][0]["prompt"]
    audio = _wave(240)
    assert _start(client, owner, request_id=key).get_json()["run"]["id"] == run["id"]
    assert _save_audio(client, other, run, audio).status_code == 404
    assert _save_report(client, owner, run).get_json()["code"] == "PILOT_AUDIO_REQUIRED"
    later = database.client.execute(
        sql.SQL("SELECT id FROM public.experiment_baseline_steps WHERE run_id = %s AND position = 2"),
        [run["id"]],
    )[0]["id"]
    assert _save_audio(client, owner, run, audio, later).get_json()["code"] == "PILOT_STEP_ORDER"
    assert client.put(_step_url(run, "audio"), headers=_headers(owner), json={"text": "a rehearsal"}).status_code == 422
    with monkeypatch.context() as m:
        m.setattr(routes, "_recording_refused",
                  lambda: (jsonify({"code": "PROCESSING_RECORDING_WITHDRAWN", "error": "Recording off"}), 403))
        assert _save_audio(client, owner, run, audio).status_code == 403
    assert _state(client, owner)["runs"]["initial"]["next_step"] == first
    assert _save_audio(client, owner, run, b"malformed media").status_code == 422
    database.client.lose_audio_response = True
    captures = []
    with monkeypatch.context() as m:
        m.setattr(sentry_sdk, "capture_exception", captures.append)
        failed = _save_audio(client, owner, run, audio)
    assert failed.status_code == 500 and failed.get_json()["code"] == "PILOT_STORE"
    assert captures == [] and PRIVATE_FAILURE_DETAIL not in (failed.get_data(as_text=True) + caplog.text)
    resumed = _state(client, owner)
    assert resumed["entry_allowed"] is False
    assert resumed["runs"]["initial"]["next_step"] == {**first, "state": "energy"}
    assert _save_audio(client, owner, run, audio).status_code == 200
    replay = client.get(_step_url(run, "audio"), headers=_headers(owner))
    assert replay.status_code == 200 and replay.data == audio
    assert replay.headers["Cache-Control"] == "private, no-store"
    assert client.get(_step_url(run, "audio"), headers=_headers(other)).status_code == 404
    assert client.get(_step_url(run, "audio")).status_code == 401
    expected_valence = {"felt_valence": "neutral"}
    assert _save_report(client, owner, run, expected_valence).status_code == 409
    assert _save_report(client, owner, run, {**REPORT, **expected_valence}).status_code == 422
    energy = _save_report(client, owner, run).get_json()
    assert energy["entry_allowed"] is False
    assert energy["run"]["next_step"] == {**first, "state": "valence"}
    assert _state(client, owner)["runs"]["initial"] == energy["run"]
    assert _save_report(client, owner, run).get_json() == energy
    assert client.get(_step_url(run, "audio"), headers=_headers(owner)).data == audio
    advanced = _save_report(client, owner, run, expected_valence).get_json()
    assert advanced["entry_allowed"] is False
    run = advanced["run"]
    second = run["next_step"]
    assert second["prompt"] == PROTOCOL["prompts"][1]["prompt"] and second["id"] == later
    assert _save_report(client, owner, run, step_id=first["id"]).get_json() == advanced
    assert _save_report(client, owner, run, expected_valence, first["id"]).get_json() == advanced
    assert _save_report(client, owner, run, {"felt_energy": "low"}, first["id"]).status_code == 409
    captured = _save_audio(client, owner, run, audio).get_json()
    assert captured["entry_allowed"] is False
    assert _state(client, owner)["runs"]["initial"]["next_step"] == {**second, "state": "energy"}
    assert _save_report(client, owner, run, {"felt_energy": "unsure"}).get_json()["entry_allowed"] is False
    final_report = {"felt_valence": "unsure"}
    completed = _save_report(client, owner, run, final_report).get_json()
    run = completed["run"]
    assert completed["entry_allowed"] is True and run["completed_at"] and run["next_step"] is None
    assert _save_report(client, owner, run, final_report, second["id"]).get_json() == completed
    stored = database.client.execute(sql.SQL("""
        SELECT intended_energy, intended_valence, felt_energy, felt_valence, partition, audio IS NOT NULL AS saved
        FROM public.experiment_baseline_steps WHERE run_id = %s ORDER BY position
    """), [run["id"]])
    assert stored == [
        {"intended_energy": intended, "intended_valence": None, "felt_energy": felt, "felt_valence": valence,
         "partition": "calibration", "saved": True}
        for intended, felt, valence in (("low", "medium_to_high", "neutral"), ("high", "unsure", "unsure"))
    ]
    assert _state(client, owner)["entry_allowed"] is True
    assert _state(client, other)["entry_allowed"] is False
    on_demand = _start(client, owner, "on_demand").get_json()["run"]
    refresh = _start(client, owner, "refresh").get_json()["run"]
    assert len({run["id"], on_demand["id"], refresh["id"]}) == 3
    assert _start(client, owner, "refresh").get_json()["code"] == "PILOT_RUN_IN_PROGRESS"
    assert client.get(API + "/runs?mode=refresh", headers=_headers(owner)).get_json()["runs"] == [refresh]


def test_prediction_inputs_and_labels_have_separate_boundaries(pilot_app):
    from services import experiment_baseline as pilot
    from services.experiment_baseline_evaluation import Audio, BlindInput, Prediction
    from services.experiment_baseline_evaluation import predict_held_out, scored_prediction
    from services.experiments import ExperimentsError

    client, database, (owner, other) = pilot_app
    initial = _start(client, owner).get_json()["run"]
    for frequency in (230, 245):
        assert _save_audio(client, owner, initial, _wave(frequency)).status_code == 200
        assert _save_report(client, owner, initial).status_code == 200
        initial = _save_report(client, owner, initial, {"felt_valence": "neutral"}).get_json()["run"]
    assert initial["completed_at"]
    # A separate synthetic evaluation run exercises the future held-out boundary.
    run_id = database.client.rpc("start_experiment_baseline", {
        "p_user_id": owner, "p_new_volunteer_id": pilot.volunteer(database, owner), "p_request_id": str(uuid.uuid4()),
        "p_mode": "on_demand", "p_protocol_version": "synthetic-evaluation-v1", "p_consent": CONSENT,
        "p_prompts": [{**prompt, "prompt_sha256": hashlib.sha256(prompt["prompt"].casefold().encode()).hexdigest()}
                      for prompt in EVALUATION_PROMPTS],
    }).execute().data
    run = _state(client, owner)["runs"]["on_demand"]
    assert run["id"] == run_id
    first, reused, target = (_wave(300), _wave(330), _wave(360))
    step_ids = []
    for audio in (first, reused, reused, target):
        step_ids.append(run["next_step"]["id"])
        assert _save_audio(client, owner, run, audio).status_code == 200
        assert _save_report(client, owner, run).status_code == 200
        run = _save_report(client, owner, run, {"felt_valence": "mixed"}).get_json()["run"]
    assert run["completed_at"]
    params = dict(user_id=owner, run_id=run_id, step_id=step_ids[-1], model_version="synthetic-probe-v1")
    assert scored_prediction(database, **params) is None
    calls = []

    def predict(data):
        calls.append(data)
        assert data == BlindInput(Audio(target, "audio/wav"), (Audio(first, "audio/wav"),))
        assert set(vars(data)) == {"recording", "calibration"}
        assert all(set(vars(audio)) == {"content", "content_type"}
                   for audio in (data.recording, *data.calibration))
        assert scored_prediction(database, **params) is None
        return Prediction("neutral", None)

    for invalid in ({**params, "user_id": other}, {**params, "step_id": step_ids[0]}):
        with pytest.raises(ExperimentsError) as rejected:
            predict_held_out(database, **invalid, predictor=predict)
        assert rejected.value.status == 404
    assert calls == []
    stored = predict_held_out(database, **params, predictor=predict)
    assert "felt_valence" not in stored and "prompt_id" not in stored
    grants = database.client.execute(sql.SQL("""
        SELECT has_table_privilege('authenticated', 'public.experiment_baseline_scored', 'SELECT') AS browser,
               has_column_privilege('service_role', 'public.experiment_baseline_steps', 'partition', 'UPDATE') AS relabel
    """), [])[0]
    assert grants == {"browser": False, "relabel": False}
    assert stored["calibration_step_ids"] == step_ids[:1]
    assert predict_held_out(database, **params, predictor=predict) == stored
    assert len(calls) == 1
    scored = scored_prediction(database, **params)
    assert scored["felt_valence"] == "mixed" and scored["felt_energy"] == "medium_to_high"
    assert scored["predicted_valence"] == "neutral" and scored["predicted_energy"] is None
    assert scored["intended_valence"] == "unpleasant"
    public = _state(client, owner)
    assert not {"predicted_valence", "predicted_energy", "calibration_step_ids", "model_version"} & public.keys()
    assert "predicted_" not in json.dumps(public)
    assert client.delete(API, headers=_headers(owner)).status_code == 200
    assert scored_prediction(database, **params) is None
    assert _state(client, owner)["entry_allowed"] is False
    assert pilot.volunteer(database, owner)


@pytest.mark.parametrize("claimed_guest", [False, True])
def test_deleted_account_cannot_restart_with_an_old_session(pilot_app, claimed_guest):
    from services import experiment_baseline as pilot

    client, database, (owner, _) = pilot_app
    request_id = str(uuid.uuid4())
    run = _start(client, owner, request_id=request_id).get_json()["run"]
    with database.client.connection.cursor() as cur:
        cur.execute("RESET ROLE")
        cur.execute("SELECT id FROM public.owner_principals WHERE user_id = %s", (owner,))
        principal = cur.fetchone()[0]
        deletion_principal = _claim_guest(cur, owner, principal) if claimed_guest else principal
        cur.execute("INSERT INTO public.account_deletion_requests VALUES (%s, 'pending')", (deletion_principal,))
        if claimed_guest:
            newer_guest = _claim_guest(cur, owner, principal)
            cur.execute("SELECT public.resolve_phase1_acquisition_principal_v1(%s, %s)", (principal, owner))
            assert cur.fetchone()[0] == newer_guest != deletion_principal
        cur.execute("SET ROLE service_role")
    assert _save_audio(client, owner, run, _wave(300)).status_code == 404
    with database.client.connection.cursor() as cur:
        cur.execute("RESET ROLE")
        cur.execute("UPDATE public.account_deletion_requests SET state = 'done' WHERE acquisition_principal_id = %s",
                    (deletion_principal,))
        cur.execute("DELETE FROM public.experiment_volunteer_keys WHERE user_id = %s", (owner,))
        cur.execute("SET ROLE service_role")
    blocked = _start(client, owner, request_id=request_id)
    assert blocked.status_code == 404 and blocked.get_json()["code"] == "PILOT_UNAVAILABLE"
    assert pilot.volunteer(database, owner) is None


def _claim_guest(cur, user, principal):
    guest = str(uuid.uuid4())
    cur.execute("INSERT INTO public.owner_principals (id) VALUES (%s)", (guest,))
    cur.execute("INSERT INTO public.owner_claim_events VALUES (%s, %s, %s, %s, clock_timestamp())",
                (str(uuid.uuid4()), guest, principal, user))
    return guest
