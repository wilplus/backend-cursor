"""
STORY    As the founder, I want each Take on a person's admin page to show what
         was said, and to export the full text to a CSV only for speakers who
         said yes to training, so that I can look for verbal patterns without
         taking words the speaker never agreed to share.
OUTCOME
  O1  A Take row carries a one-line preview of its transcript, cut at a word,
      never the whole text.
  O2  Without the training yes the export releases no text.
  O3  With the training yes it releases each Take's full transcript, and
      leaves out a Take of a project the speaker archived or erased.
PROVES   O1 -> test_a_take_row_carries_a_one_line_preview
         O2 -> test_the_export_releases_nothing_without_the_training_yes
         O3 -> test_the_export_releases_full_text_with_the_yes_and_skips_hidden_projects
WHY      Founder 2026-10-26 (WIL-110): "Go with the training-yes gate, and
         build the transcript column". Privacy 3.7 section 4 lets the person
         who runs WillpowerLab see transcripts; it names no export of them.
"""
from __future__ import annotations

from services import admin_takes, pair_consent

_LONG = "We grew in every region this year, " * 12


class _Takes:
    @staticmethod
    def list_sessions_for_user_admin(_uid):
        return [
            {"id": "t1", "arc_id": "a1", "slide_transcripts": [
                {"index": 0, "transcript": "Hello everyone."},
                {"index": 1, "transcript": _LONG}]},
            {"id": "t2", "arc_id": "a2", "slide_transcripts": [
                {"index": 0, "transcript": "A project I archived."}]},
        ]


class _Db:
    takes = _Takes()
    client = None

    @staticmethod
    def get_snippets_by_sessions(_ids):
        return {}


class _Projects:
    def __init__(self, _db):
        pass

    @staticmethod
    def erased_projects(_ids):
        return set()

    @staticmethod
    def archived_projects(_ids):
        return {"a2"}


def _wire(monkeypatch, *, yes: bool):
    monkeypatch.setattr(admin_takes, "db", _Db)
    monkeypatch.setattr(admin_takes, "_ai_clips", lambda _uid: {})
    monkeypatch.setattr(admin_takes, "_projects", lambda _ids: {})
    monkeypatch.setattr(pair_consent, "user_holds_training_yes", lambda _db, _uid: yes)
    monkeypatch.setattr("services.project_deletion.ProjectDeletionService", _Projects)


def test_a_take_row_carries_a_one_line_preview(monkeypatch):
    _wire(monkeypatch, yes=False)
    row = {r["id"]: r for r in admin_takes.takes("u1")["takes"]}["t1"]
    assert row["transcript"].startswith("Hello everyone. We grew")
    assert "\n" not in row["transcript"]
    assert row["transcript"].endswith("…") and len(row["transcript"]) <= admin_takes.PREVIEW_CHARS + 1


def test_the_export_releases_nothing_without_the_training_yes(monkeypatch):
    _wire(monkeypatch, yes=False)
    assert admin_takes.transcripts_export("u1") == {"allowed": False, "transcripts": {}}


def test_the_export_releases_full_text_with_the_yes_and_skips_hidden_projects(monkeypatch):
    _wire(monkeypatch, yes=True)
    out = admin_takes.transcripts_export("u1")
    assert out["allowed"] is True
    assert out["transcripts"] == {"t1": "Hello everyone.\n" + _LONG.strip()}
