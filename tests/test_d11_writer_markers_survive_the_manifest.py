"""A D11 writer keeps its lock preamble through every later migration.

FOUND ON A REHEARSAL CLUSTER 2026-09-25.  0327
(add_confident_moment_coaching_bundle_v1.sql) does not write its D11 lock
preambles into source text.  At migration time it reads each registered
writer with ``pg_get_functiondef``, inserts a marked preamble after ``BEGIN``
and re-executes the result.  The preamble exists only in the database, so any
later migration that re-issues one of those functions from its own source
text removes it without a word.  Two did:

  * 0335 (enable_practice_phase1_purpose.sql) re-issued
    ``accept_phase1_processing_authorization_v1``;
  * 0354 (deletion_reaches_practice_objects.sql) re-issued
    ``mark_phase1_storage_object_purged_v1``.

Production lost both preambles.  0365 re-injects them.

It stayed hidden because the rehearsal lane applied 0327 LAST, after 0354, so
the injection landed on 0354's body, and the lane never applied 0335 at all.
The marker tests passed on function states production never had.  This walk
found 0335; the rehearsal cluster had only shown 0354.

This is a STATIC guard, like tests/test_locking_functions_are_volatile.py.
It walks migrations/manifest.txt in the order the runner applies it, starting
AT 0327, and tracks for every function in 0327's registry whether the marker
is in the installed body:

  * a ``$registry$`` injection entry marks it, but a later file's entry
    counts only if it is byte-identical to 0327's (same marker, same lock
    SQL, same order);
  * a ``CREATE [OR REPLACE] FUNCTION`` of that exact signature keeps the
    mark only if its body carries the marker text;
  * a ``DROP FUNCTION`` clears it.

Starting at 0327 rather than after it matters.  0327 injects the trigger
preamble for ``advance_ideal_text_document_generation_v1()`` at its line
~1019, then re-creates that function from source at ~2061 (D19) without it.
So production has never run that trigger with its D11 locks.  That one is
listed in UNRESOLVED below and not repaired: restoring it would add lock
acquisition to every Take-ready transition and Ideal Text edit, a hot path
production has never run with these locks.  That is a founder decision, not
a repair.

After the last manifest entry, the writers left without their marker must be
exactly UNRESOLVED.  The failure names the file that removed each marker.
The fix is to carry the marker in the new body or add a re-injection like
0365's.  A writer that gets repaired must leave UNRESOLVED; the equality
check forces that.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations"
MANIFEST = MIGRATIONS / "manifest.txt"
D11_SOURCE = "add_confident_moment_coaching_bundle_v1.sql"
REASSERT = "two_d11_writers_take_their_locks_again.sql"
OBJECT_PURGE = "public.mark_phase1_storage_object_purged_v1(uuid,text,uuid,text,text,text,text)"
DOCUMENT_GENERATION = "public.advance_ideal_text_document_generation_v1()"
AUTHORIZATION_RECEIPT = (
    "public.accept_phase1_processing_authorization_v1"
    "(uuid,text,text,text,text,text,text,boolean,text,text,text,timestamptz,text)"
)

#: 0327 rewrites these two with targeted regexp edits, not through a
#: ``$registry$`` entry.  Its own verifier checks the same marker text.
LEGACY_ROOT_MARKER = "D11 legacy root writer: global inventory before root block"
LEGACY_ROOT_WRITERS = (
    "public.activate_synthetic_root_phrase_v1(uuid,uuid,boolean,boolean,text)",
    "public.remove_synthetic_root_phrase_v1(uuid,integer,integer,uuid,uuid,text)",
)

#: Writers knowingly left without their D11 marker -> the file that removed
#: it.  This may only shrink.  Each entry needs a founder decision (see the
#: module docstring).
UNRESOLVED = {DOCUMENT_GENERATION: D11_SOURCE}

_REGISTRY = re.compile(r"\$registry\$\s*(\[.*?\])\s*\$registry\$", re.DOTALL)
_CREATE = re.compile(
    r"\bCREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+(?P<name>[A-Za-z0-9_.\"]+)\s*\(",
    re.IGNORECASE,
)
_DROP = re.compile(
    r"\bDROP\s+FUNCTION\s+(?:IF\s+EXISTS\s+)?(?P<name>[A-Za-z0-9_.\"]+)\s*\(",
    re.IGNORECASE,
)
_BODY_TAG = re.compile(r"\bAS\s+(\$[A-Za-z0-9_]*\$)", re.IGNORECASE)

_MODES = {"in", "out", "inout", "variadic"}
#: First words of multi-word type names, which must not be read as a
#: parameter name.
_MULTIWORD_TYPES = {"double", "timestamp", "time", "character", "bit", "interval"}
_ALIASES = {
    "int": "integer",
    "int4": "integer",
    "int8": "bigint",
    "bool": "boolean",
    "float8": "double precision",
    "varchar": "character varying",
    "timestamp with time zone": "timestamptz",
}


def manifest_files() -> list[str]:
    """Migration file names in the order the runner applies them."""
    out: list[str] = []
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        version, _, filename = line.partition("\t")
        out.append(filename.strip())
    return out


def _blank_comments(sql: str) -> str:
    """``--`` comments replaced by spaces, so offsets still line up."""
    return re.sub(r"--[^\n]*", lambda m: " " * len(m.group(0)), sql)


def _closing_paren(sql: str, opening: int) -> int:
    depth = 0
    for index in range(opening, len(sql)):
        if sql[index] == "(":
            depth += 1
        elif sql[index] == ")":
            depth -= 1
            if depth == 0:
                return index
    raise ValueError("unbalanced parameter list")


def _split_top_level(args: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for char in args:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return [part for part in parts if part.strip()]


def _arg_type(arg: str) -> str | None:
    """The type PostgreSQL puts in the signature, or None for an OUT param."""
    text = " ".join(arg.lower().split())
    text = re.split(r"\s+default\s+|\s*=\s*", text, maxsplit=1)[0].strip()
    tokens = text.split(" ")
    if tokens[0] in _MODES:
        if tokens[0] == "out":
            return None
        tokens = tokens[1:]
    if len(tokens) > 1 and tokens[0] not in _MULTIWORD_TYPES:
        tokens = tokens[1:]
    kind = " ".join(tokens)
    return _ALIASES.get(kind, kind)


def signature(name: str, args: str) -> str:
    name = name.replace('"', "").lower()
    if "." not in name:
        name = "public." + name
    types = [t for t in (_arg_type(a) for a in _split_top_level(args)) if t]
    return f"{name}({','.join(types)})"


def registry_entries(sql: str) -> list[tuple[int, dict]]:
    """(offset, spec) for every ``$registry$`` injection entry in a file."""
    out = []
    for match in _REGISTRY.finditer(sql):
        for spec in json.loads(match.group(1)):
            if "signature" in spec and "marker" in spec:
                out.append((match.start(), spec))
    return out


def d11_registry() -> dict[str, dict]:
    """signature -> 0327's spec (marker, and the lock SQL where injected)."""
    sql = (MIGRATIONS / D11_SOURCE).read_text(encoding="utf-8")
    registry = {
        spec["signature"].replace(" ", "").lower(): spec
        for _, spec in registry_entries(sql)
    }
    for legacy in LEGACY_ROOT_WRITERS:
        registry[legacy] = {"signature": legacy, "marker": LEGACY_ROOT_MARKER}
    return registry


def function_events(sql: str) -> list[tuple[int, str, str, str]]:
    """(offset, kind, signature, body) for each CREATE / DROP FUNCTION."""
    scan = _blank_comments(sql)
    events = []
    for pattern, kind in ((_CREATE, "create"), (_DROP, "drop")):
        for match in pattern.finditer(scan):
            opening = match.end() - 1
            closing = _closing_paren(scan, opening)
            sig = signature(match.group("name"), sql[opening + 1:closing])
            body = ""
            if kind == "create":
                tag = _BODY_TAG.search(scan, closing)
                if tag:
                    start = tag.end()
                    end = sql.find(tag.group(1), start)
                    body = sql[start:end if end >= 0 else len(sql)]
            events.append((match.start(), kind, sig, body))
    return events


def walk(
    chain: list[tuple[str, str]], initially_lost: dict[str, str] | None = None
) -> dict[str, str]:
    """signature -> the file that left it without its marker, at chain end.

    ``chain`` is (file name, SQL) in manifest order.  ``initially_lost``
    names the writers that start without a marker; every other registered
    writer starts marked.  Raises AssertionError for a re-injection whose
    spec is not 0327's.
    """
    registry = d11_registry()
    lost: dict[str, str] = dict(initially_lost or {})
    for filename, sql in chain:
        events = function_events(sql)
        for offset, spec in registry_entries(sql):
            sig = spec["signature"].replace(" ", "").lower()
            if sig not in registry:
                continue
            if spec != registry[sig]:
                raise AssertionError(
                    f"{filename} re-injects {sig} with a spec that differs "
                    f"from {D11_SOURCE}'s. Copy the entry byte-for-byte."
                )
            events.append((offset, "reinject", sig, ""))
        for _, kind, sig, body in sorted(events):
            if sig not in registry:
                continue
            if kind == "reinject" or (
                kind == "create" and registry[sig]["marker"] in body
            ):
                lost.pop(sig, None)
            else:
                lost[sig] = filename
    return lost


def unmarked_writers(files: list[str]) -> dict[str, str]:
    """``walk`` over the real migration files, from 0327 on.

    Before 0327 runs, no ``$registry$`` writer is marked yet.  The two legacy
    root writers start marked: 0327 edits them without a ``$registry$`` entry,
    and its own verifier refuses to finish unless both carry the marker.
    """
    chain = files[files.index(D11_SOURCE):]
    not_yet_injected = {
        sig: D11_SOURCE
        for sig, spec in d11_registry().items()
        if "sql" in spec
    }
    return walk(
        [(f, (MIGRATIONS / f).read_text(encoding="utf-8")) for f in chain],
        not_yet_injected,
    )


class D11WriterMarkersSurviveTheManifest(unittest.TestCase):
    def test_the_registry_is_read_from_0327(self):
        registry = d11_registry()
        # 6 writers + 5 authority leaves + 3 triggers + 2 legacy root writers.
        self.assertEqual(len(registry), 16, sorted(registry))
        self.assertEqual(registry[OBJECT_PURGE]["marker"], "D11 writer: object purge")

    def test_0327_is_in_the_manifest(self):
        self.assertIn(D11_SOURCE, manifest_files())

    def test_every_registered_writer_is_marked_at_the_end_of_the_chain(self):
        lost = unmarked_writers(manifest_files())
        self.assertEqual(
            lost,
            UNRESOLVED,
            "The D11 writers left without their marker are not exactly the "
            "known UNRESOLVED set. A new entry: carry the preamble in the new "
            f"body, or add a re-injection like {REASSERT}. A missing entry: "
            f"it was repaired, so remove it from UNRESOLVED. Got: {lost}",
        )

    def test_0327_overwrites_its_own_document_generation_injection(self):
        # Walking 0327 alone: the trigger closure marks it, D19 unmarks it.
        self.assertEqual(
            unmarked_writers([D11_SOURCE]), {DOCUMENT_GENERATION: D11_SOURCE}
        )

    def test_without_0365_the_walk_names_0335_and_0354(self):
        # Shows the guard catches the production regressions it was written for.
        files = [f for f in manifest_files() if f != REASSERT]
        self.assertEqual(
            unmarked_writers(files),
            {
                **UNRESOLVED,
                AUTHORIZATION_RECEIPT: "enable_practice_phase1_purpose.sql",
                OBJECT_PURGE: "deletion_reaches_practice_objects.sql",
            },
        )

    def test_the_reinjection_follows_both_replacements(self):
        files = manifest_files()
        for replaced in (
            "enable_practice_phase1_purpose.sql",
            "deletion_reaches_practice_objects.sql",
        ):
            self.assertGreater(files.index(REASSERT), files.index(replaced))

    def test_0365_restates_the_service_role_grants_by_exact_signature(self):
        sql = " ".join((MIGRATIONS / REASSERT).read_text(encoding="utf-8").split())
        for target in (
            "ON FUNCTION public.accept_phase1_processing_authorization_v1( "
            "UUID,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,BOOLEAN,TEXT,TEXT,TEXT,TIMESTAMPTZ,TEXT )",
            "ON FUNCTION public.mark_phase1_storage_object_purged_v1( "
            "UUID,TEXT,UUID,TEXT,TEXT,TEXT,TEXT )",
        ):
            self.assertIn(
                f"REVOKE ALL {target} FROM PUBLIC, anon, authenticated;", sql
            )
            self.assertIn(f"GRANT EXECUTE {target} TO service_role;", sql)


class SignatureParsing(unittest.TestCase):
    def test_named_parameters_reduce_to_types(self):
        self.assertEqual(
            signature(
                "public.mark_phase1_storage_object_purged_v1",
                "p_purge_request_id UUID, p_source_relation TEXT, p_source_id UUID,"
                " p_storage_provider TEXT, p_bucket TEXT, p_object_key TEXT,"
                " p_exact_bytes_sha256 TEXT",
            ),
            OBJECT_PURGE,
        )

    def test_modes_defaults_and_multiword_types(self):
        self.assertEqual(
            signature(
                "f",
                "IN a timestamp with time zone, b double precision DEFAULT 1,"
                " OUT c int, d numeric(10,2) = 0",
            ),
            "public.f(timestamptz,double precision,numeric(10,2))",
        )


class TheWalkerOnSyntheticChains(unittest.TestCase):
    """The state machine, without touching the real manifest."""

    FINALIZE = "public.finalize_phase1_purge_v3(uuid,text)"

    def _walk(self, later_sql: str) -> dict[str, str]:
        return walk([("later.sql", later_sql)])

    def test_a_replacement_without_the_marker_is_flagged(self):
        sql = (
            "CREATE OR REPLACE FUNCTION public.finalize_phase1_purge_v3(\n"
            "  p_purge_request_id UUID, p_reason TEXT) RETURNS jsonb\n"
            "LANGUAGE plpgsql AS $$\nBEGIN\n RETURN NULL;\nEND;\n$$;\n"
        )
        self.assertEqual(self._walk(sql), {self.FINALIZE: "later.sql"})

    def test_a_replacement_carrying_the_marker_passes(self):
        sql = (
            "CREATE OR REPLACE FUNCTION public.finalize_phase1_purge_v3(\n"
            "  p_purge_request_id UUID, p_reason TEXT) RETURNS jsonb\n"
            "LANGUAGE plpgsql AS $$\nBEGIN\n -- D11 writer: purge finalize\n"
            " RETURN NULL;\nEND;\n$$;\n"
        )
        self.assertEqual(self._walk(sql), {})

    def test_a_marker_in_a_comment_outside_the_body_does_not_count(self):
        sql = (
            "-- D11 writer: purge finalize\n"
            "CREATE OR REPLACE FUNCTION public.finalize_phase1_purge_v3(\n"
            "  p_purge_request_id UUID, p_reason TEXT) RETURNS jsonb\n"
            "LANGUAGE plpgsql AS $fn$\nBEGIN\n RETURN NULL;\nEND;\n$fn$;\n"
        )
        self.assertEqual(self._walk(sql), {self.FINALIZE: "later.sql"})

    def test_a_reinjection_restores_the_marker(self):
        spec = d11_registry()[self.FINALIZE]
        sql = (
            "DROP FUNCTION IF EXISTS public.finalize_phase1_purge_v3(uuid, text);\n"
            "SELECT $registry$ [" + json.dumps(spec) + "] $registry$;\n"
        )
        self.assertEqual(self._walk(sql), {})

    def test_a_reinjection_with_a_different_spec_is_refused(self):
        spec = dict(d11_registry()[self.FINALIZE], sql=" PERFORM 1;\n")
        sql = "SELECT $registry$ [" + json.dumps(spec) + "] $registry$;\n"
        with self.assertRaises(AssertionError):
            self._walk(sql)

    def test_a_drop_is_flagged(self):
        sql = "DROP FUNCTION IF EXISTS public.finalize_phase1_purge_v3(uuid, text);\n"
        self.assertEqual(self._walk(sql), {self.FINALIZE: "later.sql"})


if __name__ == "__main__":
    unittest.main()
