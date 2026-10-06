"""F-3: both data doors split by the speaker's assignment, read one way.

services/speaker_split.py is the one resolver door 2 (the pair release) and
door 3 (the fine-tune run) read; the database seam reads the owner's bound
speaker and that speaker's ml_speaker_split_assignments row. The released
lane proves the binding writes the assignment
(tests/test_the_chain_hears_the_training_yes_postgres.py).
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from services import speaker_split as ss
from services.dataset_releases import speaker_split as owner_hash_split
from tests.fakes import FakeSupabaseClient, swap_attr

ROOT = Path(__file__).resolve().parents[1]


class _Reader:
    def __init__(self, rows=None, raises=None):
        self.rows = rows or {}
        self.raises = raises
        self.asked = []

    def get_speaker_splits_for_principals(self, owners, policy):
        self.asked.append((list(owners), policy))
        if self.raises:
            raise self.raises
        return self.rows


def test_the_assignment_is_read_for_the_policy_the_foundation_seeds():
    reader = _Reader({"p-1": "train", "p-2": "test"})
    assert ss.speaker_splits(reader, ["p-2", "p-1", None, "p-1"]) == {
        "p-1": "train", "p-2": "test"}
    assert reader.asked == [(["p-1", "p-2"], "speaker-sha256-80-10-10-v1")]


def test_no_reader_a_failing_read_or_a_strange_split_is_nobody_bound():
    assert ss.speaker_splits(object(), ["p-1"]) == {}
    assert ss.speaker_splits(_Reader(raises=RuntimeError("down")), ["p-1"]) == {}
    assert ss.speaker_splits(_Reader({"p-1": "holdout"}), ["p-1"]) == {}
    assert ss.speaker_splits(_Reader({"p-1": "train"}), []) == {}


def test_split_for_prefers_the_speaker_and_names_the_fallback():
    assert ss.split_for("p-1", {"p-1": "validation"}) == ("validation", "speaker_assignment")
    split, source = ss.split_for("p-1", {})
    assert (split, source) == (owner_hash_split("p-1")[0], "owner_principal_fallback")


class _RpcClient:
    """A client whose one RPC answers like get_mlc2_speaker_splits_v1."""

    def __init__(self, splits):
        self.splits = splits
        self.calls: list[tuple[str, dict]] = []

    def rpc(self, name, params):
        self.calls.append((name, params))
        rows = [{"acquisition_principal_id": p, "split": self.splits[p]}
                for p in params["p_acquisition_principal_ids"] if p in self.splits]
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=rows))


def test_the_database_seam_reads_the_split_through_one_rpc():
    from services.db import db
    client = _RpcClient({"p-1": "test"})
    with swap_attr(db, "client", client):
        out = db.get_speaker_splits_for_principals(["p-2", "p-1", "p-3", "p-1"],
                                                   "speaker-sha256-80-10-10-v1")
    assert out == {"p-1": "test"}  # p-2 has no assignment; p-3 is unbound
    (name, params), = client.calls
    assert name == "get_mlc2_speaker_splits_v1"
    assert params == {"p_acquisition_principal_ids": ["p-1", "p-2", "p-3"],
                      "p_split_policy_version": "speaker-sha256-80-10-10-v1"}


def test_the_database_seam_reads_in_chunks():
    from services.db import db
    client = _RpcClient({})
    owners = [f"p-{i:04d}" for i in range(1200)]
    with swap_attr(db, "client", client):
        assert db.get_speaker_splits_for_principals(owners, "v") == {}
    assert [len(c[1]["p_acquisition_principal_ids"]) for c in client.calls] == [500, 500, 200]


def test_no_table_is_read_directly():
    """The two ml_* tables are joined in SQL (0430): no literal table read
    that the purge registry would have to classify."""
    source = (ROOT / "services" / "db.py").read_text()
    method = source[source.index("def get_speaker_splits_for_principals("):]
    method = method[:method.index("\n    def ")]
    assert ".table(" not in method


def test_both_doors_read_the_one_resolver():
    for module in ("pair_release.py", "model_training.py"):
        source = (ROOT / "services" / module).read_text()
        assert "from services.speaker_split import" in source, module
        assert "speaker_split(owner)" not in source, module


class _Manifests:
    def __init__(self, rows=None, raises=None):
        self.rows, self.raises, self.asked = rows or {}, raises, []

    def get_pair_release_manifests(self, ids):
        self.asked.append(list(ids))
        if self.raises:
            raise self.raises
        return self.rows


def test_a_release_names_the_split_it_used():
    reader = _Manifests({"rel-new": {"split_source": "speaker_assignment"},
                         "rel-old": {"split_strategy": "speaker-sha256-80-10-10-v1"}})
    assert ss.release_split_sources(reader, ["rel-old", "rel-new", None, "rel-old"]) == {
        "rel-new": "speaker_assignment", "rel-old": "owner_principal_fallback"}
    assert reader.asked == [["rel-new", "rel-old"]]


def test_an_unreadable_release_is_no_source():
    assert ss.release_split_sources(object(), ["rel-1"]) == {}
    assert ss.release_split_sources(_Manifests(raises=RuntimeError("down")), ["rel-1"]) == {}
    assert ss.release_split_sources(_Manifests(), []) == {}


def test_the_released_split_is_the_releases_own():
    old = {"owner_principal_id": "p-1", "release_id": "rel-old"}
    new = {"owner_principal_id": "p-1", "release_id": "rel-new"}
    sources = {"rel-old": "owner_principal_fallback", "rel-new": "speaker_assignment"}
    assert ss.released_split(new, {"p-1": "validation"}, sources) == "validation"
    assert ss.released_split(old, {"p-1": "validation"}, sources) == owner_hash_split("p-1")[0]
    assert ss.released_split(new, {}, sources) is None          # assignment unreadable
    assert ss.released_split({"owner_principal_id": "p-1", "release_id": "x"}, {}, sources) is None
    assert ss.released_split({"release_id": "rel-old"}, {}, sources) is None


def test_the_database_seam_reads_release_manifests():
    from services.db import db
    client = FakeSupabaseClient({"pair_releases": [
        {"id": "rel-1", "manifest": {"split_source": "speaker_assignment"}},
        {"id": "rel-2", "manifest": None},
    ]})
    with swap_attr(db, "client", client):
        out = db.get_pair_release_manifests(["rel-2", "rel-1"])
    assert out == {"rel-1": {"split_source": "speaker_assignment"}, "rel-2": {}}

