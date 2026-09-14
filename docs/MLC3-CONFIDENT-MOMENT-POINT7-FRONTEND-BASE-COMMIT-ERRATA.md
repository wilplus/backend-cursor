# MLC-3 Confident Moment Point 7 — frontend base-commit errata

Date: 2026-09-14. Status: **errata**. It records a commit-identity change in the
frontend repository that happened *after* the Point 7 review packet was frozen.

**No packet document is modified by this note.** No executable file changes. No
re-freeze and no new review round are required — see "Why nothing is re-frozen".

## What changed

On 2026-09-14 `wilplus/frontend-cursor` had `IMG_1681.mov` removed from its
entire history:

```
git filter-repo --path IMG_1681.mov --invert-paths
```

The file was one blob, `b202c2fc85d1f437a399b7194b852851455470ce`, 82.2 MB,
present in **1280 of 1944 commits** since `2026-05-02`. All 242 branches were
force-pushed. A fresh clone went from 97.15 MiB to ~13.4 MiB.

File *contents* are unchanged everywhere. Only commit identity moved.

Verified by execution before the push:

| Check | Result |
| --- | --- |
| `main^{tree}` before vs after | identical — `c4fb18d32cab3d59fc1aff1be0bd1b716c97ca62` |
| 242 branch tips, old tree vs new tree | 234 differ **only** by `IMG_1681.mov`, 8 byte-identical, **0** unexpected differences |
| `IMG_1681` objects in a fresh clone afterwards | 0 |

## The mapping

| Referenced in the packet as | Now |
| --- | --- |
| `0f88bd4a3f96d0f39c6679a232a1a32837f0dde6` (frontend base) | `8a244e6352acd3b99f5f5b9f28ad020837925418` |
| `af81da6e4a73c86bb3de64879894bda1defa8eee` (the commit that added the file) | `1a3d71b9f8f46c8c96b08c2d116b183c13547871` |

`8a244e63` is `feat: add disabled MLC-3 general-user practice flow (#348)`,
2026-09-10, and is an ancestor of both the Point 7 frontend branch head and the
current `main`. `0f88bd4a` is no longer reachable from any branch on `origin`;
it may persist in GitHub's retained `refs/pull/*` refs, which `git clone` does
not fetch.

Branch tip: `claude/confident-moment-point7-release` `daa4e5169349c3c190cd6b38b5268196a0a47380`
→ `39b38f375c201a5496fe82ab3ed4470baf8e9445`.

The complete 1944-entry old→new commit map was produced by the rewrite and held
by the founder. Any other pre-rewrite frontend SHA resolves through it.

## Documents that pin the old value — deliberately not edited

| File | Line |
| --- | --- |
| `docs/MLC3-CONFIDENT-MOMENT-POINT7-IMPLEMENTATION-EVIDENCE.md` | 8 |
| `docs/MLC3-CONFIDENT-MOMENT-POINT7-FRONTEND-SHA256.txt` | 3 |
| `docs/MLC3-CONFIDENT-MOMENT-COACHING-CONTRACT-DELTA-D3.md` | 18 |
| `docs/CLAUDE-HANDOFF-CONFIDENT-MOMENT-POINT7-2026-09-12.md` | 23 |
| `docs/MLC3-CONFIDENT-MOMENT-COACHING-INTERFACE-MANIFEST-D6.md` | 24 |

They keep the old SHA on purpose. The packet's own rule is that files are never
modified after the packet is produced, and that any change requires new hashes
and a new packet. A pointer that moved underneath a frozen document is recorded
here; it is not rewritten there.

## Why nothing is re-frozen

`docs/MLC3-CONFIDENT-MOMENT-POINT7-FRONTEND-SHA256.txt` lists 34 files. Verified
against the rewritten Point 7 head `39b38f37`:

```
verified: 34   mismatched: 0   missing: 0
```

Method: for each manifest entry,
`git cat-file blob 39b38f37:<path> | sha256sum`, compared to the listed value.

This is the expected result. The manifest hashes file *contents*, and the
rewrite changed no file content — it removed one unrelated file and, as a
consequence, renumbered every commit that carried it. Only the "Base commit"
line in that manifest refers to something that moved.

**Reading note for anyone re-running the check:** the manifest's hashes are of
the delivered files at the Point 7 *branch head*, not at the base commit.
Verifying against the base commit alone reports every entry as missing or
mismatched, because most of those files do not exist there yet. That is a
method error, not a manifest failure.

## Scope

- No executable file changed. No re-freeze; no repeat of engineering or ML/data
  acceptance.
- Backend history was not rewritten. `docs/MLC3-CONFIDENT-MOMENT-POINT7-BACKEND-SHA256.txt`
  is unaffected.
- Migration `0327` and its ledger row are untouched; they live in this
  repository, not the frontend.
- Nothing is activated by this note. The D49 §5 activation attestation remains
  outstanding and is unaffected by the rewrite.
