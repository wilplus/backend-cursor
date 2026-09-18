"""Every code citation in the counsel pack must still resolve.

WHY THIS EXISTS (2026-09-18). `legal/phase1-2026.1/09-counsel-cover-note.md`
tells outside counsel that "the technical sections are verifiable line by line
against the repository", and `docs/legal/AI-ACT-SCOPING-MEMO.md` says its §2 is
"verified against source". Those are promises about a moving codebase made in
documents that, once signed, become immutable fingerprinted rows
(`register_phase1_policy_v1`) and cannot be edited afterwards.

They had already rotted before anyone looked. On 2026-09-18 the DPIA cited
`services/voice_confidence.py:177` twice for the `VOICE_CONFIDENCE_ENABLED`
default; line 177 was a comment separator and the flag had moved to :256. The
RISK-11 call sites pointed two functions away from where they had ended up.
A lawyer following either one lands on code that does not say what the document
says it says, which is worse than no citation at all — it reads as a client who
described the system inaccurately.

WHAT THIS CHECKS. Only that a citation still points at something: the file
exists, the line is inside it, and the line is not blank or a bare comment rule
(the exact shape `:177` had degenerated into). It cannot check that the line
still MEANS what the document claims — no test can. It buys the cheap half,
which is the half that rots silently.

SCOPE. The pack that goes to counsel, and nothing else. Frontend citations are
skipped for content because that repository is not checked out here; they are
required to name a commit instead, which is the convention
`accepted-versions/README.md` already uses and the only form that stays true
after the file changes.
"""
from __future__ import annotations

import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: The documents that are sent to counsel. Keep in step with the cover note.
PACK_GLOB_DIR = os.path.join("legal", "phase1-2026.1")
PACK_EXTRA = (
    os.path.join("docs", "legal", "AI-ACT-SCOPING-MEMO.md"),
    os.path.join("docs", "legal", "DPIA-2026-09-17.md"),
    os.path.join("docs", "legal", "ROPA-ART30.md"),
)

# `tsx` before `ts`: leftmost alternation would otherwise match "page.ts" out of
# "page.tsx" and report a live file as missing.
_EXT = r"(?:tsx|ts|py|sql|json|txt|sh|md|mjs)"
_CITE = re.compile(r"`([A-Za-z0-9_][A-Za-z0-9_/.-]*\." + _EXT + r")((?::\d+(?:-\d+)?)*)[^`]*`")
_LINES = re.compile(r":(\d+)(?:-(\d+))?")

# Citations into the frontend repository, which is not checked out here.
_FRONTEND = ("frontend-cursor/", "src/app/")


def _pack_docs() -> list[str]:
    docs = []
    for root, _dirs, files in os.walk(os.path.join(REPO, PACK_GLOB_DIR)):
        docs += [os.path.join(root, f) for f in files if f.endswith(".md")]
    docs += [os.path.join(REPO, p) for p in PACK_EXTRA]
    return sorted(docs)


def _resolve(path: str, doc: str) -> str | None:
    """Repo-relative first, then relative to the citing document's directory."""
    for candidate in (path, os.path.join(os.path.dirname(doc), path)):
        full = os.path.normpath(os.path.join(REPO, candidate))
        if os.path.isfile(full) and full.startswith(REPO):
            return full
    return None


def _citations():
    for doc in _pack_docs():
        with open(doc, encoding="utf-8") as handle:
            for doc_line, text in enumerate(handle, 1):
                for match in _CITE.finditer(text):
                    yield doc, doc_line, match.group(1), match.group(2) or ""


def test_every_cited_path_in_the_counsel_pack_exists():
    """A dead path in a document a lawyer is asked to sign is a factual error."""
    missing = []
    for doc, doc_line, path, _lines in _citations():
        if path.startswith(_FRONTEND) or "/" not in path:
            continue  # other repo, or a bare filename used in prose
        if _resolve(path, doc) is None:
            missing.append(f"{os.path.relpath(doc, REPO)}:{doc_line} -> {path}")
    assert not missing, "cited files do not exist:\n  " + "\n  ".join(missing)


def test_every_cited_line_is_real_and_not_blank():
    """`:177` pointed at a bare `#` for a day. That is the failure to catch."""
    broken = []
    for doc, doc_line, path, lines in _citations():
        if path.startswith(_FRONTEND):
            continue
        full = _resolve(path, doc)
        if full is None:
            continue  # the test above owns missing files
        with open(full, encoding="utf-8", errors="replace") as handle:
            source = handle.readlines()
        for start, end in _LINES.findall(lines):
            first, last = int(start), int(end or start)
            where = f"{os.path.relpath(doc, REPO)}:{doc_line} -> {path}:{start}"
            if last > len(source):
                broken.append(f"{where} (file has {len(source)} lines)")
                continue
            # A range legitimately spans blank rows inside a docstring table, so
            # it only has to contain something. A bare `:N` has one chance to be
            # the line that carries the fact, which is the check that matters.
            body = [line.strip().strip("#─-= ") for line in source[first - 1:last]]
            if not any(body):
                broken.append(f"{where} (blank or bare comment rule)")
    assert not broken, "citations point at nothing:\n  " + "\n  ".join(broken)


def test_frontend_citations_name_a_commit():
    """The frontend copy changes under the pack; only a commit stays true.

    `08-RECONCILIATION.md` cites text that has since been corrected on the live
    site. Without a commit those line numbers now resolve to unrelated copy, and
    counsel reads a false statement we are asserting we made.
    """
    unpinned = []
    for doc, doc_line, path, lines in _citations():
        if not path.startswith(_FRONTEND) or not lines:
            continue
        with open(doc, encoding="utf-8") as handle:
            body = handle.readlines()
        window = "".join(body[max(0, doc_line - 6):doc_line + 5])
        if not re.search(r"`[0-9a-f]{7,40}`", window):
            unpinned.append(f"{os.path.relpath(doc, REPO)}:{doc_line} -> {path}{lines}")
    assert not unpinned, (
        "frontend citations with a line number but no nearby commit:\n  "
        + "\n  ".join(unpinned))


# Commits cited in the pack that live in `wilplus/frontend-cursor`, verified
# against a FULL clone of it on 2026-09-18 (both clones ship shallow at 50
# commits, which is why an earlier pass could not resolve any of them and had to
# say so rather than call them broken). Each is an ancestor of that repo's
# `main`. Listed explicitly because this repository cannot reach that one: an
# unlisted hash is therefore treated as a backend hash and must resolve here.
#
# Matched by prefix in either direction, because the pack cites the same commit
# at seven and at eight characters.
_FRONTEND_COMMITS = (
    "3202b5a1",  # 2026-05-07  legal pages first ship
    "9815b7a2",  # 2026-06-06  WillpowerLab rebrand
    "01026bf0",  # 2026-07-24  Terms + Privacy v1.0
    "9a5a1a85",  # 2026-08-13  Legal v1.1 (#288)
    "f97ad632",  # 2026-08-13  v1.1 pages
    "7a46c279",  # 2026-08-28  v1.2
    "179600c4",  # 2026-09-17  pages render the stored bytes (#384)
    "162b340a",  # 2026-09-17  drop the fallback banner (#385)
    "15d95706",  # 2026-09-17  zero-data-retention + data-sharing correction (#386)
    "9f740756",  # 2026-09-18  last revision holding "opt-in and off by default"
    "f4607888",  # 2026-09-18  acceptance screen (#389)
)


def _is_frontend(sha: str) -> bool:
    return any(sha.startswith(k) or k.startswith(sha) for k in _FRONTEND_COMMITS)

# Backticked hex that is not a commit reference.
_NOT_A_COMMIT = {"604800"}

_HASH = re.compile(r"`([0-9a-f]{7,40})`")


def test_every_cited_commit_is_reachable_from_this_branch():
    """A squash-merge destroys the working-branch hash the pack was drafted from.

    Two citations were dead when this was written. `81369c0`, named in the AI Act
    determination §9 as the commit that renamed the band labels — the section
    counsel reads immediately before ticking `emotion_intention_inference` — was
    in neither repository; the rename shipped as `e5e02d6`. `8f3e51d7`, named in
    `accepted-versions/README.md` as the correction of six false statements, is
    on an unmerged branch and is not the text that went live.

    Both are the same failure: this repository squash-merges, so a hash taken
    from a branch stops existing the moment the PR lands. A lawyer given the pack
    cannot resolve one, and nothing in the document says it should not be there.
    """
    if os.path.exists(os.path.join(REPO, ".git", "shallow")):
        import pytest
        pytest.skip("shallow clone: absent objects would be a false positive")

    import subprocess
    dead = []
    for doc, doc_line, sha in {
        (doc, doc_line, m.group(1))
        for doc in _pack_docs()
        for doc_line, text in enumerate(open(doc, encoding="utf-8"), 1)
        for m in _HASH.finditer(text)
    }:
        if _is_frontend(sha) or sha in _NOT_A_COMMIT:
            continue
        # A hash may be named precisely to say it is NOT on main — that is the
        # correction, not the defect. The exemption is earned by the document
        # saying so at the point of use, not by a list kept here.
        body = open(doc, encoding="utf-8").readlines()
        if "not on `main`" in "".join(body[max(0, doc_line - 4):doc_line + 3]):
            continue
        where = f"{os.path.relpath(doc, REPO)}:{doc_line} -> {sha}"
        kind = subprocess.run(["git", "cat-file", "-t", sha], cwd=REPO,
                              capture_output=True, text=True)
        if kind.stdout.strip() != "commit":
            dead.append(f"{where} (no such commit here, and not a listed frontend commit)")
            continue
        reachable = subprocess.run(["git", "merge-base", "--is-ancestor", sha, "HEAD"],
                                   cwd=REPO, capture_output=True)
        if reachable.returncode != 0:
            dead.append(f"{where} (exists but is not an ancestor of HEAD)")
    assert not dead, "commits a reader could not resolve:\n  " + "\n  ".join(sorted(dead))
