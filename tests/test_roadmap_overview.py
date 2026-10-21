"""
STORY    As the founder, I want one page that shows where each planned piece
         of work stands, read from GitHub, so that I see progress without
         asking anyone or ticking anything by hand.
OUTCOME
  O1  An item carried by an open PR reads "in review", by a draft PR
      "draft", and "done" only when every PR that finishes it is merged.
  O2  A merged part alone never reads "done"; a branch with no PR reads
      "in progress"; nothing found reads "not started".
  O3  A Linear id in the title of a PR opened since the plan's date ties
      that PR to its item; an older PR with the same id does not.
  O4  When GitHub cannot be read, every item reads "unknown" and none
      reads "done".
PROVES   O1 -> test_open_draft_and_merged_prs_set_the_state
         O2 -> test_parts_branches_and_nothing_found
         O3 -> test_a_linear_id_ties_only_recent_prs
         O4 -> test_github_down_shows_unknown_not_done
"""
import httpx

from services import roadmap

PLAN = {
    "since": "2026-10-20",
    "versions": [{
        "key": "1.1", "name": "Fast and true", "line": "",
        "items": [
            {"id": "review", "title": "In review", "prs": [{"repo": "backend", "number": 10}]},
            {"id": "drafted", "title": "Drafted", "prs": [{"repo": "backend", "number": 11}]},
            {"id": "shipped", "title": "Shipped", "prs": [{"repo": "backend", "number": 12},
                                                          {"repo": "frontend", "number": 5}]},
            {"id": "half", "title": "Half shipped", "prs": [{"repo": "backend", "number": 12},
                                                            {"repo": "backend", "number": 10}]},
            {"id": "part", "title": "A part is in", "parts": [{"repo": "backend", "number": 12}]},
            {"id": "branch", "title": "On a branch", "branches": [{"repo": "frontend", "name": "claude/x"}]},
            {"id": "nothing", "title": "Nothing yet", "keywords": ["D13"]},
            {"id": "linked", "title": "Linked by id", "wil": ["WIL-76"]},
        ],
    }],
}


def _pr(number, state="open", draft=False, merged_at=None, title="", created="2026-10-21T09:00:00Z"):
    return {"number": number, "title": title, "state": state, "draft": draft, "merged_at": merged_at,
            "html_url": f"https://github.com/x/pull/{number}", "head": {"ref": f"b{number}"},
            "created_at": created}


def _fetch(backend, frontend=(), branches=()):
    def fetch(path):
        if "/branches/" in path:
            return {"name": "x"} if any(path.endswith(b.replace("/", "%2F")) for b in branches) else None
        if "/pulls?" in path:
            rows = backend if "backend-cursor" in path else frontend
            return [r for r in rows if "state=all" in path or r["state"] == "open"]
        return None
    return fetch


def _states(payload):
    return {i["id"]: i["state"] for v in payload["versions"] for i in v["items"]}


MERGED = "2026-10-21T10:00:00Z"


def test_open_draft_and_merged_prs_set_the_state():
    backend = [_pr(10), _pr(11, draft=True), _pr(12, state="closed", merged_at=MERGED)]
    frontend = [_pr(5, state="closed", merged_at=MERGED)]
    states = _states(roadmap.overview(fetch=_fetch(backend, frontend), plan=PLAN))
    assert states["review"] == "in_review"
    assert states["drafted"] == "draft"
    assert states["shipped"] == "done"
    assert states["half"] == "in_review"


def test_parts_branches_and_nothing_found():
    backend = [_pr(12, state="closed", merged_at=MERGED)]
    states = _states(roadmap.overview(fetch=_fetch(backend, branches=["claude/x"]), plan=PLAN))
    assert states["part"] == "in_progress"
    assert states["branch"] == "in_progress"
    assert states["nothing"] == "not_started"


def test_a_linear_id_ties_only_recent_prs():
    old = [_pr(20, title="Speed: the walk (WIL-76)", created="2026-10-12T09:00:00Z")]
    assert _states(roadmap.overview(fetch=_fetch(old), plan=PLAN))["linked"] == "not_started"
    recent = [_pr(21, title="Speed: the walk opens first (WIL-76)")]
    assert _states(roadmap.overview(fetch=_fetch(recent), plan=PLAN))["linked"] == "in_review"


def test_github_down_shows_unknown_not_done():
    def down(path):
        raise httpx.ConnectError("no route")
    payload = roadmap.overview(fetch=down, plan=PLAN)
    assert payload["ok"] is False
    assert set(_states(payload).values()) == {"unknown"}
