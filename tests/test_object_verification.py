"""F-8: every download or release check appends a verification.

Unit cases for services/object_verification.py and its callers (the weekly
job, which reads door 2's new releases back right after its export and
checks every standing one, and the dark training-corpus copy). Door 2's
export path itself is unchanged. The database's judgement is played by a
fake that compares exactly as 0431's writers do; the released lane executes
the writers themselves (tests/test_the_chain_hears_the_training_yes_postgres.py).
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from unittest import mock

import pytest

from services import object_verification as ov
from services import pair_release as pr

KEY = "k" * 32
WHOLE = b"the whole take, as it was promoted"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def writing(monkeypatch):
    """The chain writes (founder_canary, no ring kill) unless a test says not."""
    state = {"on": True}
    monkeypatch.setattr(ov, "chain_writes_enabled", lambda: state["on"])
    return state


class _ChainDb:
    """ml_object_artifacts and the 0431 writer, judged as the SQL judges."""

    def __init__(self, artifacts=None, due=None):
        self.artifacts = artifacts or {("lab", "take.webm"): (_sha(WHOLE), len(WHOLE))}
        self.due = due if due is not None else [
            {"object_artifact_id": "a-1", "bucket": "lab", "object_key": "take.webm",
             "last_checked_at": None}]
        self.rows: list[dict] = []
        self.limits: list[int] = []

    def record_mlc2_object_verification(self, *, bucket, object_key, observed_sha256,
                                        observed_byte_size, verification_method,
                                        verifier_version):
        expected = self.artifacts.get((bucket, object_key))
        if expected is None:
            return None
        row = {"verified": (observed_sha256, observed_byte_size) == expected,
               "method": verification_method, "version": verifier_version,
               "sha": observed_sha256, "size": observed_byte_size}
        self.rows.append(row)
        return {"verification_id": f"v-{len(self.rows)}", "verified": row["verified"]}

    def list_mlc2_objects_due_verification(self, limit):
        self.limits.append(limit)
        return self.due


class TestNoteDownload:
    def test_a_chain_object_download_appends_what_was_read(self, writing):
        db = _ChainDb()
        out = ov.note_download(db, bucket="lab", object_key="take.webm", data=WHOLE)
        assert out["verified"] is True
        assert db.rows == [{"verified": True, "method": "download_sha256",
                            "version": ov.VERIFIER_VERSION, "sha": _sha(WHOLE),
                            "size": len(WHOLE)}]

    def test_changed_bytes_are_appended_unverified(self, writing):
        db = _ChainDb()
        assert ov.note_download(db, bucket="lab", object_key="take.webm",
                                data=b"other")["verified"] is False

    def test_another_key_writes_nothing(self, writing):
        db = _ChainDb()
        assert ov.note_download(db, bucket="lab", object_key="x.webm", data=WHOLE) is None
        assert db.rows == []

    def test_nothing_is_written_while_the_chain_is_not_writing(self, writing):
        writing["on"] = False
        db = _ChainDb()
        assert ov.note_download(db, bucket="lab", object_key="take.webm", data=WHOLE) is None
        assert db.rows == []

    def test_a_failing_write_never_fails_the_download(self, writing):
        db = mock.Mock()
        db.record_mlc2_object_verification.side_effect = RuntimeError("rpc down")
        assert ov.note_download(db, bucket="lab", object_key="take.webm", data=WHOLE) is None

    def test_no_writer_or_no_bytes_is_nothing(self, writing):
        assert ov.note_download(object(), bucket="lab", object_key="k", data=WHOLE) is None
        assert ov.note_download(_ChainDb(), bucket="lab", object_key="take.webm",
                                data=None) is None


def test_the_gate_is_the_chains_own_writer_state(monkeypatch):
    from services import mlc2_confidence_cutover as cutover
    for mode, expected in (("founder_canary", True), ("killed", False), ("dark", False)):
        monkeypatch.setattr(cutover, "configured_confidence_cutover",
                            lambda m=mode: cutover.resolve_confidence_cutover(m))
        assert ov.chain_writes_enabled() is expected

    def broken():
        raise RuntimeError("ring read failed")
    monkeypatch.setattr(cutover, "configured_confidence_cutover", broken)
    assert ov.chain_writes_enabled() is False


class TestTheWeeklyObjectCheck:
    def test_each_due_object_is_downloaded_once_and_counted(self, writing):
        due = [{"bucket": "lab", "object_key": "take.webm"},
               {"bucket": "lab", "object_key": "changed.webm"},
               {"bucket": "lab", "object_key": "gone.webm"}]
        db = _ChainDb(artifacts={("lab", "take.webm"): (_sha(WHOLE), len(WHOLE)),
                                 ("lab", "changed.webm"): (_sha(WHOLE), len(WHOLE)),
                                 ("lab", "gone.webm"): (_sha(WHOLE), len(WHOLE))},
                      due=due)
        bodies = {"take.webm": WHOLE, "changed.webm": b"changed"}

        def fetch(bucket, key):
            if key not in bodies:
                raise FileNotFoundError(key)
            return bodies[key]
        out = ov.check_chain_objects(db, fetch=fetch)
        assert out == {"checked": 2, "verified": 1, "mismatched": 1, "failed": 1}
        assert [row["method"] for row in db.rows] == ["scheduled_check_sha256"] * 2
        assert db.limits == [ov.WEEKLY_OBJECT_LIMIT]

    def test_nothing_is_downloaded_while_the_chain_is_not_writing(self, writing):
        writing["on"] = False
        fetch = mock.Mock()
        out = ov.check_chain_objects(_ChainDb(), fetch=fetch)
        assert out["checked"] == 0 and "not writing" in out["why"]
        fetch.assert_not_called()

    def test_an_unreadable_list_is_named(self, writing):
        db = mock.Mock()
        db.list_mlc2_objects_due_verification.side_effect = RuntimeError("down")
        assert "down" in ov.check_chain_objects(db, fetch=mock.Mock())["unavailable"]
        assert "unavailable" in ov.check_chain_objects(object())

    def test_the_counts_name_no_key(self, writing):
        out = ov.check_chain_objects(_ChainDb(), fetch=lambda b, k: WHOLE)
        assert "take.webm" not in json.dumps(out)


# ── Door 2 ────────────────────────────────────────────────────────────────

class _Config:
    MLC2_PAIR_RELEASES_ENABLED = True
    PAIR_RELEASE_SURFACES = frozenset({"praise_line"})
    R2_PAIR_RELEASE_BUCKET = "willab-pair-releases"
    PAIR_RELEASE_SIGNING_KEY = KEY
    PAIR_RELEASE_SIGNING_KEY_ID = "pair-release-key-1"


class _Storage:
    def __init__(self):
        self.objects: dict[tuple[str, str], bytes] = {}
        self.reads: list[tuple[str, str]] = []

    def put(self, bucket, key, body, content_type):
        self.objects[(bucket, key)] = body

    def delete(self, bucket, key):
        self.objects.pop((bucket, key), None)

    def get(self, bucket, key):
        self.reads.append((bucket, key))
        return self.objects[(bucket, key)]


class _ReleaseDb:
    """A one-surface door 2 ledger and the 0431 release writer, judged as
    the SQL judges (file against file_sha256; manifest against
    manifest_sha256 and the signature)."""

    def __init__(self, recorder_fails=False):
        self.releases: list[dict] = []
        self.checks: list[dict] = []
        self.recorder_fails = recorder_fails

    def list_releasable_pairs(self, surface, limit=5000):
        return [{"id": "pair-1", "surface": surface, "draft_text": "d", "final_text": "f",
                 "final_kind": "final", "owner_principal_id": "p-1",
                 "consent_policy_version": "training-v1",
                 "created_at": "2026-10-01T00:00:00+00:00"}]

    def get_speaker_splits_for_principals(self, owners, policy):
        return {"p-1": "train"}

    # The release decides each pair afresh (PLF-P5): the yes in force now,
    # the service not ending, the Take's project (none here).
    def list_active_training_grants(self, owners):
        return [{"id": "grant-p-1", "acquisition_principal_id": "p-1",
                 "consent_policy_version": "training-v1"}]

    def phase1_learning_stopped(self, owner):
        return False

    def list_take_projects(self, takes):
        return {}

    def insert_pair_release(self, **fields):
        row = {"id": f"rel-{len(self.releases) + 1}", **fields}
        self.releases.append(row)
        return row

    def insert_pair_release_owners(self, release_id, owners):
        return len(owners)

    def mark_feedback_pairs_released(self, release_id, pair_ids):
        return len(pair_ids)

    def list_live_pair_releases(self):
        return [{k: r[k] for k in ("id", "storage_bucket", "storage_key")}
                for r in self.releases]

    def record_pair_release_verification(self, *, release_id, object_role,
                                         observed_sha256, observed_byte_size,
                                         signature_valid, verification_method,
                                         verifier_version):
        if self.recorder_fails:
            raise RuntimeError("rpc down")
        release = next(r for r in self.releases if r["id"] == release_id)
        if object_role == "file":
            assert signature_valid is None
            verified = observed_sha256 == release["file_sha256"]
        else:
            assert signature_valid is not None
            verified = observed_sha256 == release["manifest_sha256"] and signature_valid
        self.checks.append({"release_id": release_id, "role": object_role,
                            "method": verification_method, "verified": verified,
                            "size": observed_byte_size})
        return {"verified": verified}


def _export(db, storage):
    return pr.export_surface(db, storage, surface="praise_line",
                             week_start=date(2026, 10, 5), config=_Config(),
                             now=datetime(2026, 10, 5, 6, tzinfo=timezone.utc))


FILE_KEY = ("willab-pair-releases", "pair-releases/praise_line/2026-10-05/pairs.jsonl")
MANIFEST_KEY = ("willab-pair-releases", "pair-releases/praise_line/2026-10-05/manifest.json")


class TestTheReleaseIsReadBack:
    def test_both_objects_are_read_back_and_judged_right_after_the_write(self):
        db, storage = _ReleaseDb(), _Storage()
        out = _export(db, storage)
        assert "verified" not in out            # the export path is unchanged
        assert ov.read_back_exports(db, storage, _Config(), [out]) == {"rel-1"}
        assert out["verified"] is True
        assert storage.reads == [FILE_KEY, MANIFEST_KEY]
        assert [(c["role"], c["method"], c["verified"]) for c in db.checks] == [
            ("file", "read_after_write_sha256", True),
            ("manifest", "read_after_write_sha256", True)]
        assert db.checks[0]["size"] == len(storage.objects[FILE_KEY])

    def test_a_check_that_cannot_run_never_holds_the_release_back(self):
        db, storage = _ReleaseDb(recorder_fails=True), _Storage()
        out = _export(db, storage)
        assert ov.read_back_exports(db, storage, _Config(), [out]) == set()
        assert out["exported"] == 1 and out["verified"] is None
        assert len(db.releases) == 1

    def test_a_row_without_a_release_is_left_alone(self):
        db, storage = _ReleaseDb(), _Storage()
        stayed = {"surface": "praise_line", "exported": 0, "why": "door 2 closed"}
        assert ov.read_back_exports(db, storage, _Config(), [stayed]) == set()
        assert "verified" not in stayed and db.checks == []

    def test_an_unreadable_ledger_or_storage_is_no_check(self):
        db, storage = _ReleaseDb(), _Storage()
        out = _export(db, storage)
        broken = mock.Mock(wraps=db)
        broken.list_live_pair_releases.side_effect = RuntimeError("down")
        assert ov.read_back_exports(broken, storage, _Config(), [out]) == set()
        assert out["verified"] is None

        class _WriteOnly:
            def __init__(self):
                self.objects = {}

            def put(self, bucket, key, body, content_type):
                self.objects[(bucket, key)] = body
        db = _ReleaseDb()
        out = _export(db, _WriteOnly())
        assert ov.read_back_exports(db, _WriteOnly(), _Config(), [out]) == set()
        assert out["verified"] is None and db.checks == []


class TestTheWeeklyReleaseCheck:
    def _released(self):
        db, storage = _ReleaseDb(), _Storage()
        _export(db, storage)
        db.checks.clear()
        storage.reads.clear()
        return db, storage

    def test_every_standing_release_is_checked_again(self):
        db, storage = self._released()
        out = ov.check_pair_releases(db, storage, _Config())
        assert out == {"checked": 1, "verified": 1, "mismatched": [], "failed": []}
        assert [c["method"] for c in db.checks] == ["scheduled_check_sha256"] * 2

    def test_a_release_read_back_this_run_is_not_read_twice(self):
        db, storage = self._released()
        out = ov.check_pair_releases(db, storage, _Config(), skip={"rel-1"})
        assert out["checked"] == 0 and db.checks == [] and storage.reads == []

    def test_a_changed_file_is_a_mismatch_on_the_record(self):
        db, storage = self._released()
        storage.objects[FILE_KEY] += b'{"pair_id": "smuggled"}\n'
        out = ov.check_pair_releases(db, storage, _Config())
        assert out["mismatched"] == ["rel-1"]
        assert [c["verified"] for c in db.checks] == [False, True]

    def test_a_tampered_manifest_or_another_key_fails_the_signature(self):
        db, storage = self._released()
        manifest = json.loads(storage.objects[MANIFEST_KEY])
        manifest["item_count"] = 2
        storage.objects[MANIFEST_KEY] = json.dumps(manifest).encode()
        assert ov.check_pair_releases(db, storage, _Config())["mismatched"] == ["rel-1"]
        db, storage = self._released()

        class _Other(_Config):
            PAIR_RELEASE_SIGNING_KEY = "other"
        assert ov.check_pair_releases(db, storage, _Other())["mismatched"] == ["rel-1"]

    def test_a_missing_object_is_named_and_retried(self):
        db, storage = self._released()
        storage.objects.pop(FILE_KEY)
        out = ov.check_pair_releases(db, storage, _Config())
        assert out["failed"] == ["rel-1"] and out["checked"] == 0

    def test_an_unreadable_ledger_is_named(self):
        db = mock.Mock()
        db.list_live_pair_releases.side_effect = RuntimeError("down")
        assert "down" in ov.check_pair_releases(db, _Storage(), _Config())["unavailable"]
        assert "unavailable" in ov.check_pair_releases(object(), _Storage(), _Config())


class TestTheManifestReading:
    def test_the_export_manifest_reads_back_as_signed(self):
        db, storage = _ReleaseDb(), _Storage()
        out = _export(db, storage)
        observed, valid = ov.manifest_reading(storage.objects[MANIFEST_KEY], KEY)
        assert (observed, valid) == (out["manifest_sha256"], True)

    def test_garbage_is_never_valid(self):
        for body in (b"\xff\xfe", b"[1, 2]", b"not json"):
            observed, valid = ov.manifest_reading(body, KEY)
            assert valid is False and observed == _sha(body)
        assert ov.manifest_reading(b"{}", "")[1] is False


def test_the_release_bucket_is_read_through_its_r2_client():
    """R2ReleaseStorage keeps its two verbs; the read-back reads through the
    same client the export writes with."""
    storage = pr.R2ReleaseStorage(_Config())
    assert not hasattr(storage, "get")
    client = mock.Mock()
    client.get_object.return_value = {"Body": mock.Mock(read=lambda: b"bytes")}
    storage._client = client
    assert ov._read(storage, "b", "k") == b"bytes"
    client.get_object.assert_called_once_with(Bucket="b", Key="k")


def test_the_weekly_job_checks_before_it_reads_the_health():
    from services import learning_weekly as lw
    order: list[str] = []
    db = mock.Mock()
    exported = [{"surface": "praise_line", "exported": 3, "release_id": "rel-9"}]

    def read_back(database, storage, config, rows):
        order.append("read_back")
        rows[0]["verified"] = True
        return {"rel-9"}

    def releases(database, storage, config, skip):
        order.append("releases")
        assert skip == {"rel-9"}
        return {"checked": 0}
    with mock.patch("services.object_verification.read_back_exports", side_effect=read_back), \
         mock.patch("services.object_verification.check_pair_releases", side_effect=releases), \
         mock.patch("services.object_verification.check_chain_objects",
                    side_effect=lambda *a: order.append("objects") or {"checked": 0}), \
         mock.patch.object(lw, "foundation_health",
                           side_effect=lambda d: order.append("health") or {}), \
         mock.patch.object(lw, "_export_pairs", return_value=exported), \
         mock.patch.object(lw, "_training_pass", return_value={}), \
         mock.patch("services.pair_release.sweep_voided", return_value={"purged": 0}), \
         mock.patch("services.pair_consent.refresh", return_value={}), \
         mock.patch("services.learning_ledger.ledger", return_value={
             "ledger_version": "v", "pairs": {}, "shadow_cues": {}, "unavailable": []}):
        report = lw.run_weekly(db, config=_Config(), now=datetime(2026, 10, 5, tzinfo=timezone.utc))
    assert order == ["read_back", "releases", "objects", "health"]
    assert report["verifications"] == {"read_back": 1, "pair_releases": {"checked": 0},
                                       "chain_objects": {"checked": 0}}
    assert report["exported"][0]["verified"] is True
    stored = db.upsert_ledger_snapshot.call_args.kwargs
    assert stored["snapshot"]["verifications"] == report["verifications"]
    assert stored["exported"][0]["verified"] is True


def test_a_failing_step_is_named_and_the_other_still_runs():
    from services import learning_weekly as lw
    with mock.patch("services.object_verification.read_back_exports",
                    side_effect=RuntimeError("ledger away")), \
         mock.patch("services.object_verification.check_pair_releases",
                    side_effect=RuntimeError("bucket away")), \
         mock.patch("services.object_verification.check_chain_objects",
                    return_value={"checked": 1}):
        out = lw._verification_pass(object(), _Storage(), _Config(), [])
    assert out["read_back"] == 0
    assert "bucket away" in out["pair_releases"]["unavailable"]
    assert out["chain_objects"] == {"checked": 1}
