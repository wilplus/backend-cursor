"""The shadow writer must accept the frame the V3 picker actually builds.

public.record_take_feedback_policy_v3_shadow_v3 is redefined by migrations.
The last definition in migrations/manifest.txt is the one that runs. It must
accept the policy, frame schema, and suggestion-generator versions the code
in services.take_feedback_policy_v3 builds. No database: this reads the SQL.
"""

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.take_feedback_policy_v3 import (  # noqa: E402
    FRAME_SCHEMA_VERSION,
    POLICY_VERSION,
    SUGGESTION_GENERATOR_CONTRACT_VERSION,
)

MANIFEST_PATH = REPO_ROOT / "migrations" / "manifest.txt"
FUNCTION_RE = re.compile(
    r"CREATE\s+OR\s+REPLACE\s+FUNCTION\s+"
    r"public\.record_take_feedback_policy_v3_shadow_v3\s*\(",
    re.IGNORECASE,
)
DOLLAR_QUOTE_RE = re.compile(r"\$([A-Za-z0-9_]*)\$")
COMPARISON_RE = re.compile(
    r"(?:IS\s+(?:NOT\s+)?DISTINCT\s+FROM"
    r"|<>"
    r"|!="
    r"|(?<![<>!])=(?!=)"
    r"|NOT\s+IN"
    r"|(?<![\w])IN(?![\w]))"
    r"\s*(?:ALL\b\s*)?(?:ANY\b\s*)?\(?\s*(?:ARRAY\s*\[)?\s*"
    r"(?P<lits>'(?:[^']|'')*'(?:\s*,\s*'(?:[^']|'')*')*)",
    re.IGNORECASE,
)
BOUNDARY_RE = re.compile(
    r"\b(?:OR|AND|THEN|ELSIF|ELSE|BEGIN|END)\b",
    re.IGNORECASE,
)


def _strip_sql_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    sql = re.sub(r"--[^\n]*", " ", sql)
    return sql


def _manifest_entries():
    text = MANIFEST_PATH.read_text(encoding="utf-8")
    entries = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "\t" in line:
            _version, filename = line.split("\t", 1)
            filename = filename.strip()
        else:
            filename = stripped
        entries.append(filename)
    return entries


def _migration_path(filename: str) -> Path:
    direct = REPO_ROOT / filename
    if direct.is_file():
        return direct
    return REPO_ROOT / "migrations" / filename


def _function_body(sql: str):
    """Last CREATE OR REPLACE of the shadow function, through its closing dollar quote."""
    sql = _strip_sql_comments(sql)
    found = None
    for match in FUNCTION_RE.finditer(sql):
        quote = DOLLAR_QUOTE_RE.search(sql, match.end())
        if quote is None:
            continue
        tag = quote.group(0)
        close_at = sql.find(tag, quote.end())
        if close_at < 0:
            continue
        found = sql[match.start() : close_at + len(tag)]
    return found


def _latest_shadow_definition():
    latest = None
    for filename in _manifest_entries():
        path = _migration_path(filename)
        if not path.is_file():
            continue
        body = _function_body(path.read_text(encoding="utf-8"))
        if body is not None:
            latest = (path.name, body)
    if latest is None:
        pytest.fail(
            "No migration listed in migrations/manifest.txt redefines "
            "public.record_take_feedback_policy_v3_shadow_v3."
        )
    return latest


def _cut_predicate(after_key: str) -> str:
    """Keep the boolean term that checks this key; do not cross OR/AND/THEN."""
    depth = 0
    in_string = False
    i = 0
    # The key is often the inside of a quoted operator or path. Skip that closer.
    if after_key.startswith("'"):
        i = 1
    while i < len(after_key):
        ch = after_key[i]
        if in_string:
            if ch == "'":
                if i + 1 < len(after_key) and after_key[i + 1] == "'":
                    i += 2
                    continue
                in_string = False
            i += 1
            continue
        if ch == "'":
            in_string = True
            i += 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif depth == 0:
            boundary = BOUNDARY_RE.match(after_key, i)
            if boundary and i > 0:
                return after_key[:i]
            if ch == ";":
                return after_key[:i]
        i += 1
    return after_key


def _sql_string_literals(fragment: str):
    return [
        match.group(1).replace("''", "'")
        for match in re.finditer(r"'((?:[^']|'')*)'", fragment)
    ]


def _accepted_literals(body: str, key: str):
    """Literals the function treats as acceptable for this key.

    Covers a single comparison (IS DISTINCT FROM 'v', <> 'v') and a list
    (NOT IN ('v3', 'v5'), <> ALL (ARRAY['v3', 'v5']), = ANY (ARRAY[...])).
    """
    accepted = []
    for match in re.finditer(re.escape(key), body):
        predicate = _cut_predicate(body[match.end() : match.end() + 600])
        comparison = COMPARISON_RE.search(predicate)
        if comparison is None:
            continue
        for literal in _sql_string_literals(comparison.group("lits")):
            if literal.startswith("{") or literal == key:
                continue
            if literal not in accepted:
                accepted.append(literal)
    return accepted


def _quoted(values):
    if not values:
        return "no version"
    return " or ".join(repr(value) for value in values)


def test_shadow_writer_accepts_the_frame_schema_the_code_builds():
    filename, body = _latest_shadow_definition()
    accepted = _accepted_literals(body, "frame_schema_version")
    assert FRAME_SCHEMA_VERSION in accepted, (
        f"Migration {filename} does not accept the frame schema version the code builds. "
        f"public.record_take_feedback_policy_v3_shadow_v3 accepts "
        f"{_quoted(accepted)} for frame_schema_version, "
        f"but the code builds {FRAME_SCHEMA_VERSION!r}."
    )


def test_shadow_writer_requires_the_policy_version_the_code_builds():
    filename, body = _latest_shadow_definition()
    accepted = _accepted_literals(body, "p_policy_version")
    assert POLICY_VERSION in accepted, (
        f"Migration {filename} does not require the policy version the code builds. "
        f"public.record_take_feedback_policy_v3_shadow_v3 requires "
        f"{_quoted(accepted)} for p_policy_version, "
        f"but the code builds {POLICY_VERSION!r}."
    )


def test_shadow_writer_accepts_the_suggestion_generator_contract_the_code_builds():
    filename, body = _latest_shadow_definition()
    accepted = _accepted_literals(body, "suggestion_generator_contract_version")
    assert SUGGESTION_GENERATOR_CONTRACT_VERSION in accepted, (
        f"Migration {filename} does not accept the suggestion generator contract "
        f"the code builds. public.record_take_feedback_policy_v3_shadow_v3 accepts "
        f"{_quoted(accepted)} for suggestion_generator_contract_version, "
        f"but the code builds {SUGGESTION_GENERATOR_CONTRACT_VERSION!r}."
    )
