"""The founder's roadmap (founder 2026-10-21): where each planned piece of
work stands, read live from the two GitHub repositories.

The plan lives in ``config/roadmap.json``: versions, each a list of items,
and for each item the signals that tie it to code. ``prs`` finish the item,
``parts`` are only part of it, ``wil`` ids and ``keywords`` match PR titles
opened on or after ``since``, and ``branches`` count before a PR exists.
A PR that starts or finishes an item adds its number there.

An item's state is read off GitHub, never set by hand:
  in_review    an open PR carries it
  draft        only a draft PR carries it
  done         every PR that finishes it is merged
  in_progress  a part is merged, or its branch exists with no PR yet
  not_started  nothing found
  unknown      GitHub could not be read

Founder page only; nothing here reaches a speaker. Both repositories are
public, so GitHub is read without a token: every list is fetched with its
ETag (an unchanged list costs nothing against the hourly limit) and the
whole read is cached for five minutes.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Sequence
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

PLAN_PATH = Path(__file__).resolve().parent.parent / "config" / "roadmap.json"
REPOS = {"backend": "wilplus/backend-cursor", "frontend": "wilplus/frontend-cursor"}
CACHE_SECONDS = 300
MERGED_SHOWN = 12

#: path ("/repos/...") -> parsed JSON, or None for a 404. Raises when GitHub
#: cannot be read.
Fetch = Callable[[str], Any]

_lock = threading.Lock()
_etags: dict[str, tuple[str, Any]] = {}
_finished_prs: dict[tuple[str, int], dict] = {}
_cache: dict[str, Any] = {}


def github_get(path: str) -> Any:
    url = f"https://api.github.com{path}"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "willpowerlab-roadmap"}
    known = _etags.get(url)
    if known:
        headers["If-None-Match"] = known[0]
    response = httpx.get(url, headers=headers, timeout=15)
    if response.status_code == 304 and known:
        return known[1]
    if response.status_code == 404:
        return None
    response.raise_for_status()
    body = response.json()
    etag = response.headers.get("ETag")
    if etag:
        _etags[url] = (etag, body)
    return body


def load_plan() -> dict:
    return json.loads(PLAN_PATH.read_text(encoding="utf-8"))


def _items(plan: dict) -> list[dict]:
    return [item for version in plan.get("versions", []) for item in version.get("items", [])]


def _pr(repo: str, raw: dict) -> dict:
    if raw.get("merged_at"):
        state = "merged"
    elif raw.get("state") == "open":
        state = "draft" if raw.get("draft") else "open"
    else:
        state = "closed"
    return {
        "repo": repo,
        "number": int(raw["number"]),
        "title": str(raw.get("title") or ""),
        "state": state,
        "url": str(raw.get("html_url") or ""),
        "branch": str((raw.get("head") or {}).get("ref") or ""),
        "created_at": str(raw.get("created_at") or ""),
        "merged_at": str(raw.get("merged_at") or ""),
    }


def read_github(fetch: Fetch, plan: dict) -> dict:
    """Every open PR and the 100 most recently updated, per repository;
    then any PR the plan names that neither list holds (a finished one is
    kept, since it cannot change); then the branches the plan names."""
    prs: dict[tuple[str, int], dict] = {}
    for repo, full in REPOS.items():
        for state in ("open", "all"):
            rows = fetch(f"/repos/{full}/pulls?state={state}&sort=updated&direction=desc&per_page=100") or []
            for raw in rows:
                pr = _pr(repo, raw)
                prs[(repo, pr["number"])] = pr
    branches: dict[tuple[str, str], bool] = {}
    for item in _items(plan):
        for ref in list(item.get("prs", [])) + list(item.get("parts", [])):
            _add_named_pr(fetch, prs, str(ref["repo"]), int(ref["number"]))
        for ref in item.get("branches", []):
            key = (str(ref["repo"]), str(ref["name"]))
            if key not in branches:
                path = f"/repos/{REPOS[key[0]]}/branches/{quote(key[1], safe='')}"
                branches[key] = fetch(path) is not None
    return {"prs": prs, "branches": branches}


def _add_named_pr(fetch: Fetch, prs: dict, repo: str, number: int) -> None:
    key = (repo, number)
    if key in prs:
        return
    if key in _finished_prs:
        prs[key] = _finished_prs[key]
        return
    raw = fetch(f"/repos/{REPOS[repo]}/pulls/{number}")
    if not raw:
        return
    pr = _pr(repo, raw)
    prs[key] = pr
    if pr["state"] in ("merged", "closed"):
        _finished_prs[key] = pr


def _mentions(pr: dict, item: dict, since: str) -> bool:
    if pr["created_at"][:10] < since:
        return False
    title = pr["title"].lower()
    for wil in item.get("wil", []):
        if re.search(rf"\b{re.escape(wil.lower())}\b", f"{title} {pr['branch'].lower()}"):
            return True
    return any(word.lower() in title for word in item.get("keywords", []))


def _unique(prs: Sequence[Optional[dict]]) -> list[dict]:
    seen: dict[tuple[str, int], dict] = {}
    for pr in prs:
        if pr:
            seen.setdefault((pr["repo"], pr["number"]), pr)
    return list(seen.values())


def _label(pr: dict) -> str:
    return f"{pr['repo']} #{pr['number']}"


def _day(iso: str) -> str:
    try:
        moment = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return f"{moment.day} {moment:%b}"
    except ValueError:
        return ""


def item_state(item: dict, github: dict, since: str) -> dict:
    prs, branches = github["prs"], github["branches"]
    finishing = _unique(
        [prs.get((str(r["repo"]), int(r["number"]))) for r in item.get("prs", [])]
        + [pr for pr in prs.values() if _mentions(pr, item, since)]
        + [pr for pr in prs.values()
           if any(pr["repo"] == b["repo"] and pr["branch"] == b["name"] for b in item.get("branches", []))]
    )
    parts = _unique([prs.get((str(r["repo"]), int(r["number"]))) for r in item.get("parts", [])])
    live = [pr for pr in finishing if pr["state"] != "closed"]
    every = _unique(live + parts)
    open_ = [pr for pr in every if pr["state"] == "open"]
    drafts = [pr for pr in every if pr["state"] == "draft"]
    if open_:
        return _state("in_review", f"Waiting for review in {_label(open_[0])}.", open_ + drafts)
    if drafts:
        return _state("draft", f"Being written in {_label(drafts[0])}; not ready for review yet.", drafts)
    if live and all(pr["state"] == "merged" for pr in live):
        last = max(live, key=lambda pr: pr["merged_at"])
        return _state("done", f"Done. {_label(last)} merged on {_day(last['merged_at'])}.", live)
    merged_parts = [pr for pr in parts if pr["state"] == "merged"]
    if merged_parts:
        return _state("in_progress", f"Part of it is in ({_label(merged_parts[0])}); the rest is not started.", merged_parts)
    if any(branches.get((str(b["repo"]), str(b["name"]))) for b in item.get("branches", [])):
        return _state("in_progress", "Started on a branch; no pull request yet.", [])
    return _state("not_started", "Not started yet.", [])


def _state(state: str, note: str, prs: list[dict]) -> dict:
    links = [{"label": _label(pr), "url": pr["url"]} for pr in prs[:3] if pr["url"]]
    return {"state": state, "note": note, "links": links}


def build(plan: dict, github: Optional[dict], problem: Optional[str] = None) -> dict:
    since = str(plan.get("since") or "")
    versions = []
    for version in plan.get("versions", []):
        items = []
        for item in version.get("items", []):
            status = (item_state(item, github, since) if github
                      else _state("unknown", "GitHub could not be read just now.", []))
            items.append({"id": item["id"], "title": item["title"], "why": item.get("why", ""), **status})
        versions.append({
            "key": version["key"], "name": version["name"], "line": version.get("line", ""),
            "done": sum(1 for i in items if i["state"] == "done"), "total": len(items), "items": items,
        })
    merged = sorted((pr for pr in (github or {}).get("prs", {}).values() if pr["state"] == "merged"),
                    key=lambda pr: pr["merged_at"], reverse=True)[:MERGED_SHOWN]
    return {
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ok": github is not None,
        "problem": problem,
        "versions": versions,
        "merged": [{k: pr[k] for k in ("repo", "number", "title", "merged_at", "url")} for pr in merged],
    }


def overview(fetch: Optional[Fetch] = None, plan: Optional[dict] = None) -> dict:
    """The page's whole read. With no ``fetch`` it reads GitHub itself and
    serves the cached read for five minutes. When GitHub fails it serves the
    last good read, marked, or else every item as unknown: nothing is ever
    shown as done without GitHub saying so."""
    plan = plan if plan is not None else load_plan()
    shared = fetch is None
    with _lock:
        cached, at = _cache.get("payload"), float(_cache.get("at") or 0)
    if shared and cached and time.time() - at < CACHE_SECONDS:
        return cached
    try:
        payload = build(plan, read_github(fetch or github_get, plan))
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        logger.warning("roadmap: GitHub read failed: %s", exc)
        if shared and cached:
            return {**cached, "ok": False, "problem": "GitHub did not answer; this is the last good check."}
        return build(plan, None, problem="GitHub did not answer; try again in a few minutes.")
    if shared:
        with _lock:
            _cache.update(payload=payload, at=time.time())
    return payload
