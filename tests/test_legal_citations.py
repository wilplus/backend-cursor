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
