"""
STORY    As the founder, I want stored files from the old era deleted and then
         checked as gone, never assumed gone, so that the erasure record is
         true.
OUTCOME
  O1  Preview deletes nothing and records nothing; execute deletes, then
      checks the file is absent, and only then records "deleted".
  O2  A file still there after its delete raises, and nothing is recorded
      for it.
  O3  A provider error while checking raises (it is never read as
      "absent"), and nothing is recorded for it.
PROVES   O1 -> test_preview_keeps_and_execute_deletes_then_confirms
         O2 -> test_a_file_still_there_raises_unrecorded
         O3 -> test_a_provider_error_raises_unrecorded
WHY      F4 storage step (scripts/bundled_era_erasure_storage.py drives
         services.bundled_era_storage.run). Storage and the database are
         replaced by in-memory fakes.
"""
from __future__ import annotations

from functools import partial
from types import SimpleNamespace

import pytest

from services.bundled_era_storage import Place, resolve, run

REF = "s3://b/k/x.webm"
PLACE = Place("r2", "b", "k/x.webm")


class _Db:
    """The two RPCs run() calls: the snapshot's refs, and each outcome."""

    def __init__(self):
        self.recorded = []
        self.client = SimpleNamespace(rpc=self._rpc)

    def _rpc(self, name, params):
        if name == "bundled_era_erasure_storage_refs_v1":
            return SimpleNamespace(execute=lambda: SimpleNamespace(data=[REF]))
        assert name == "record_bundled_era_object_v1"
        self.recorded.append((params["p_ref"], params["p_outcome"]))
        return SimpleNamespace(execute=lambda: None)


class _Bucket:
    def __init__(self, *, delete_works=True, provider_error=False):
        self.present, self.calls = {PLACE}, []
        self.delete_works, self.provider_error = delete_works, provider_error

    def is_absent(self, place):
        self.calls.append("check")
        if self.provider_error:
            raise ConnectionError("provider timed out")
        return place not in self.present

    def delete(self, place):
        self.calls.append("delete")
        if self.delete_works:
            self.present.discard(place)


def _run(bucket, *, execute):
    database = _Db()
    resolver = partial(resolve, is_absent=bucket.is_absent, delete=bucket.delete)
    result = run(database, "snap-1", execute=execute, export_refs=[], resolver=resolver)
    return result, database.recorded


def test_preview_keeps_and_execute_deletes_then_confirms():
    bucket = _Bucket()
    preview, recorded = _run(bucket, execute=False)
    assert preview["tally"] == {"would_delete": 1}
    assert recorded == [] and bucket.present == {PLACE}
    assert "delete" not in bucket.calls
    bucket.calls.clear()
    done, recorded = _run(bucket, execute=True)
    assert done["tally"] == {"deleted": 1}
    assert recorded == [(REF, "deleted")]
    assert bucket.calls == ["check", "delete", "check"]


def test_a_file_still_there_raises_unrecorded():
    bucket = _Bucket(delete_works=False)
    database = _Db()
    resolver = partial(resolve, is_absent=bucket.is_absent, delete=bucket.delete)
    with pytest.raises(RuntimeError, match="still present after delete"):
        run(database, "snap-1", execute=True, export_refs=[], resolver=resolver)
    assert database.recorded == []


def test_a_provider_error_raises_unrecorded():
    bucket = _Bucket(provider_error=True)
    database = _Db()
    resolver = partial(resolve, is_absent=bucket.is_absent, delete=bucket.delete)
    with pytest.raises(ConnectionError):
        run(database, "snap-1", execute=True, export_refs=[], resolver=resolver)
    assert database.recorded == [] and "delete" not in bucket.calls
