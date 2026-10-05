"""B1-5: the owner edits a Paragraph, then Take 2 rewrites the Slide — on a
real database, through the Python production runs.

Contract 8 (as amended 2026-10-03, N29), 9, 14 and 16; founder N48.1 Wave 1
step 7. Each later Take rewrites every Slide it spoke from exactly what was
said on it in that Take, owner edits included; a Slide it did not speak keeps
its last version; locked helper words persist until the user picks new ones;
nothing is lost, because every version stays in history.

WHAT RUNS, AND HOW. Every write and read below is the production code path,
against the disposable `take-rewrite` lane (scripts/rehearsal_tier.sh):

  Take 1      `mint_machine_parts` + `DatabaseService.replace_ideal_text_parts`
              (the publish path's minting of Paragraph identity);
  helper      `slide_helper_words.pick` / `.lock` + `replace_slide_helper_words`
  words       (the route's `_apply`, with the Slide known), and
              `set_ideal_text_part_root` / `set_ideal_text_part_lock`;
  the edit    `DatabaseService.compare_and_set_user_ideal_edit` ->
              `compare_and_set_user_ideal_edit_v1`, the one owner-edit writer,
              exactly as the legacy PUT sends it;
  Take 2      `services.take_review.finalize_later_take_review`: the rebuild
              plan, `finalize_ideal_text_take_v2`, the fresh-read proof, and
              `apply_after_finalize` (identity, `take_rewrite` revisions,
              helper words).

Two seams are replaced, and only two. `build_transcript_document` returns
Take 2's transcript document (turning audio and snippets into that document is
transcription, not what is under test here); `publish_for_arc` is recorded
instead of run (the cold-open read model has its own lane). The Supabase
client is a thin shim that turns its PostgREST calls into SQL, as the account
deletion rehearsal does; it runs as the lane's owner, because this suite
asserts behaviour, not grants.
"""
from __future__ import annotations

import os
import uuid
from typing import Any

import psycopg2
import psycopg2.extras
import pytest
from psycopg2 import sql

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable take-rewrite rehearsal only"
)

# Take 1's words, Slide by Slide, and what the owner made of the first one.
SLIDE0_TAKE1 = "We shipped it in March."
SLIDE1_TAKE1 = "Nobody believed the numbers until they saw them."
SLIDE0_EDITED = "We shipped it in March, ahead of plan."
# Take 2 speaks Slide 0 only, in words that no longer hold its helper words.
SLIDE0_TAKE2 = "We launched in March and the plan held."
SLIDE0_WORDS = "ahead of plan"
SLIDE1_WORDS = "saw them"


# --------------------------------------------------------------------------- #
#  PostgREST -> SQL shim (the slice of the builder the code under test uses)  #
# --------------------------------------------------------------------------- #
class _Result:
    def __init__(self, data: Any) -> None:
        self.data = data


def _value(value: Any) -> Any:
    """A mapping or a list is JSONB, as PostgREST coerces it."""
    if isinstance(value, (dict, list)):
        return psycopg2.extras.Json(value)
    return value


class _Query:
    def __init__(self, client: "_SqlClient", relation: str) -> None:
        self.client, self.relation = client, relation
        self.columns = "*"
        self.filters: list[tuple[str, Any]] = []
        self.orders: list[tuple[str, bool]] = []
        self.cap: int | None = None
        self.mode = "select"
        self.payload: Any = None

    def select(self, columns: str = "*") -> "_Query":
        self.columns = columns
        return self

    def insert(self, payload: Any) -> "_Query":
        self.mode, self.payload = "insert", payload
        return self

    def update(self, payload: dict) -> "_Query":
        self.mode, self.payload = "update", payload
        return self

    def delete(self) -> "_Query":
        self.mode = "delete"
        return self

    def eq(self, column: str, value: Any) -> "_Query":
        self.filters.append((column, value))
        return self

    def order(self, column: str, desc: bool = False) -> "_Query":
        self.orders.append((column, desc))
        return self

    def limit(self, count: int) -> "_Query":
        self.cap = count
        return self

    def _where(self) -> tuple[sql.Composable, list]:
        if not self.filters:
            return sql.SQL(""), []
        return (sql.SQL(" WHERE ") + sql.SQL(" AND ").join(
            sql.SQL("{}::text = %s").format(sql.Identifier(c))
            for c, _ in self.filters), [str(v) for _, v in self.filters])

    def execute(self) -> _Result:
        table = sql.SQL("public.{}").format(sql.Identifier(self.relation))
        where, args = self._where()
        if self.mode == "insert":
            rows = self.payload if isinstance(self.payload, list) else [self.payload]
            out: list[dict] = []
            for row in rows:
                cols = list(row)
                out += self.client.fetch(
                    sql.SQL("INSERT INTO {} ({}) VALUES ({}) RETURNING *").format(
                        table, sql.SQL(",").join(map(sql.Identifier, cols)),
                        sql.SQL(",").join(sql.Placeholder() * len(cols))),
                    [_value(row[c]) for c in cols])
            return _Result(out)
        if self.mode == "update":
            assert self.filters, "an unfiltered UPDATE never reaches the database"
            cols = list(self.payload)
            return _Result(self.client.fetch(
                sql.SQL("UPDATE {} SET {}{} RETURNING *").format(
                    table, sql.SQL(",").join(
                        sql.SQL("{} = %s").format(sql.Identifier(c)) for c in cols),
                    where),
                [_value(self.payload[c]) for c in cols] + args))
        if self.mode == "delete":
            assert self.filters, "an unfiltered DELETE never reaches the database"
            return _Result(self.client.fetch(
                sql.SQL("DELETE FROM {}{} RETURNING *").format(table, where), args))
        columns = (sql.SQL("*") if self.columns.strip() == "*" else
                   sql.SQL(",").join(sql.Identifier(c.strip())
                                     for c in self.columns.split(",")))
        query = sql.SQL("SELECT {} FROM {}{}").format(columns, table, where)
        if self.orders:
            query += sql.SQL(" ORDER BY ") + sql.SQL(",").join(
                sql.SQL("{} DESC" if desc else "{}").format(sql.Identifier(c))
                for c, desc in self.orders)
        if self.cap:
            query += sql.SQL(" LIMIT {}").format(sql.Literal(self.cap))
        return _Result(self.client.fetch(query, args))


class _Rpc:
    def __init__(self, client: "_SqlClient", name: str, params: dict) -> None:
        self.client, self.name, self.params = client, name, params

    def execute(self) -> _Result:
        keys = list(self.params)
        query = sql.SQL("SELECT * FROM public.{}({})").format(
            sql.Identifier(self.name), sql.SQL(", ").join(
                sql.SQL("{} => %s").format(sql.Identifier(k)) for k in keys))
        rows = self.client.fetch(query, [_value(self.params[k]) for k in keys])
        if len(rows) == 1 and list(rows[0]) == [self.name]:
            return _Result(rows[0][self.name])
        return _Result(rows)


class _SqlClient:
    def __init__(self, connection) -> None:
        self.connection = connection

    def table(self, relation: str) -> _Query:
        return _Query(self, relation)

    def rpc(self, name: str, params: dict) -> _Rpc:
        return _Rpc(self, name, params)

    def fetch(self, query, args) -> list[dict]:
        with self.connection.cursor(
            cursor_factory=psycopg2.extras.RealDictCursor,
        ) as cur:
            cur.execute(query, args)
            return [dict(row) for row in cur.fetchall()] if cur.description else []


def _database(connection):
    from services.db import DatabaseService

    service = DatabaseService.__new__(DatabaseService)
    service.client = _SqlClient(connection)
    service._v2_sessions_missing_columns = set()
    return service


# --------------------------------------------------------------------------- #
#  Fixtures                                                                   #
# --------------------------------------------------------------------------- #
def _connect():
    parsed = psycopg2.extensions.parse_dsn(DSN)
    if not parsed.get("dbname", "").startswith("willab_confident_moment_"):
        raise RuntimeError("Refusing a non-disposable database")
    if not str(parsed.get("host", "")).startswith("/tmp/willab-"):
        raise RuntimeError("Refusing a host outside the disposable cluster")
    return psycopg2.connect(DSN)


def _rows(conn, statement, args=()) -> list[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(statement, args)
        return [dict(r) for r in cur.fetchall()] if cur.description else []


def _document(paragraphs: list[tuple[int, str]], take_session_id: str,
              take_index: int) -> tuple[str, dict]:
    """A transcript document in `build_transcript_document`'s shape."""
    text, pieces, paras, cursor = [], [], [], 0
    for n, (slide, words) in enumerate(paragraphs):
        cursor += 2 if n else 0
        span = {"start": cursor, "end": cursor + len(words)}
        pieces.append({**span, "text": words, "slide_index": slide,
                       "snippet_id": str(uuid.uuid4()),
                       "take_session_id": take_session_id,
                       "take_index": take_index})
        paras.append({**span, "slide_index": slide,
                      "take_session_id": take_session_id,
                      "take_index": take_index})
        text.append(words)
        cursor += len(words)
    joined = "\n\n".join(text)
    return joined, {"text": joined, "pieces": pieces, "paragraphs": paras,
                    "take_session_id": take_session_id,
                    "take_index": take_index}


@pytest.fixture
def speaker():
    """An owner whose Project has an Ideal Text from Take 1 (two Slides)."""
    from tests.test_confident_moment_coaching_bundle_postgres import (
        _positive_projection_context,
    )

    setup = _connect()
    try:
        context, _feedback = _positive_projection_context(setup)
        setup.commit()
    finally:
        setup.close()
    conn = _connect()
    conn.autocommit = True
    try:
        owner = _rows(conn, "SELECT user_id::text u FROM owner_principals WHERE id=%s",
                      (context["owner"],))[0]["u"]
        arc = str(context["project"])
        take1 = _rows(conn, """SELECT source_take_session_id::text t
            FROM ideal_text_document_snapshots WHERE project_id=%s AND version=1""",
                      (context["project"],))[0]["t"]
        take2 = str(uuid.uuid4())
        _rows(conn, "UPDATE v2_sessions SET arc_id=%s WHERE id=%s", (arc, take1))
        _rows(conn, """INSERT INTO v2_sessions
                (id, arc_id, user_id, owner_principal_id, project_id, take_index,
                 recording_kind)
            VALUES (%s, %s, %s, %s, %s, 2, 'spoken')""",
              (take2, arc, owner, context["owner"], context["project"]))
        # Take 1 wrote the document, its Slide map and its version snapshot.
        text1, doc1 = _document([(0, SLIDE0_TAKE1), (1, SLIDE1_TAKE1)], take1, 1)
        _rows(conn, """INSERT INTO coach_arc_ideal_text
                (arc_id, text, auto_text, version, document, auto_updated_at)
            VALUES (%s, %s, %s, 1, %s, now())""",
              (arc, text1, text1, psycopg2.extras.Json(doc1)))
        _rows(conn, """INSERT INTO ideal_text_versions (arc_id, version, text, document)
            VALUES (%s, 1, %s, %s)""", (arc, text1, psycopg2.extras.Json(doc1)))
        database = _database(conn)
        yield {"conn": conn, "db": database, "arc": arc, "owner": owner,
               "take1": take1, "take2": take2}
    finally:
        conn.close()


def _parts(s) -> list[dict]:
    return _rows(s["conn"], """SELECT id::text, ord, text, locked_at, root_phrase
        FROM ideal_text_part WHERE arc_id=%s AND user_id=%s ORDER BY ord""",
                 (s["arc"], s["owner"]))


def _choose_and_lock(s, part_id: str, slide: int, phrase: str) -> None:
    """The helper-words step: the pick and the lock, as the routes write
    them (the Paragraph's own phrase and lock, and the Slide's set)."""
    from services import slide_helper_words as words

    database = s["db"]
    text = next(p["text"] for p in _parts(s) if p["id"] == part_id)
    start = text.index(phrase)
    assert database.set_ideal_text_part_root(
        arc_id=s["arc"], user_id=s["owner"], part_id=part_id, phrase=phrase,
        start=start, end=start + len(phrase))
    assert database.set_ideal_text_part_lock(s["arc"], s["owner"], part_id, True)
    rows = [r for r in database.get_slide_helper_words(s["arc"], s["owner"])
            if r.get("slide_index") == slide]
    rows = words.pick(rows, take_id=s["take1"], part_id=part_id, phrase=phrase)
    rows = words.lock(rows, take_id=s["take1"], part_id=part_id, locked=True,
                      live_parts={part_id.lower()})
    assert database.replace_slide_helper_words(s["arc"], s["owner"], slide, rows)


def _edit(s, texts: list[tuple[str, str]]) -> dict:
    """The owner's edit, sent as the legacy PUT sends it: the full text and
    the full Paragraph list, against the version on screen (1)."""
    text = "\n\n".join(t for _, t in texts)
    result = s["db"].compare_and_set_user_ideal_edit(
        owner_user_id=s["owner"], arc_id=s["arc"], source_document_version=1,
        expected_user_text_revision=None, expected_user_text_sha256=None,
        desired_user_text=text,
        desired_parts_lineage=[{"id": pid, "ord": n, "text": t}
                               for n, (pid, t) in enumerate(texts)],
        idempotency_key=None)
    assert result["saved"] is True
    return result


def _take_two(s, monkeypatch, spoken: list[tuple[int, str]]) -> dict:
    """Take 2 finalizes, through the production finalizer."""
    import services.ideal_text_core_snapshot as core
    import services.transcript_document as transcript
    from services.take_review import finalize_later_take_review

    _text, doc2 = _document(spoken, s["take2"], 2)
    published: list = []
    monkeypatch.setattr(transcript, "build_transcript_document",
                        lambda arc_id, *, database=None, session_id=None: doc2)
    monkeypatch.setattr(core, "publish_for_arc",
                        lambda database, arc_id, actor_id=None, **_: published.append(arc_id))
    receipt = finalize_later_take_review(
        s["db"], arc_id=s["arc"], owner_user_id=s["owner"],
        take_session_id=s["take2"], take_index=2)
    assert published == [s["arc"]]
    return receipt


def _take_one_paragraphs(s) -> tuple[str, str]:
    """Take 1's Paragraph identity, minted as the publish path mints it."""
    from services.ideal_text_parts import mint_machine_parts

    minted = mint_machine_parts(f"{SLIDE0_TAKE1}\n\n{SLIDE1_TAKE1}")
    assert minted and s["db"].replace_ideal_text_parts(s["arc"], s["owner"], minted)
    first, second = (p["id"] for p in _parts(s))
    return first, second


# --------------------------------------------------------------------------- #
#  The walk                                                                   #
# --------------------------------------------------------------------------- #
def test_take_two_rewrites_the_edited_slide_and_keeps_the_rest(speaker, monkeypatch):
    s = speaker
    first, second = _take_one_paragraphs(s)

    # Slide 1's helper words are chosen and locked; then the owner edits the
    # Paragraph on Slide 0 and locks helper words in the edited words.
    _choose_and_lock(s, second, 1, SLIDE1_WORDS)
    edit = _edit(s, [(first, SLIDE0_EDITED), (second, SLIDE1_TAKE1)])
    assert [r["action"] for r in edit["part_revisions"]] == ["owner_part_text_updated"]
    _choose_and_lock(s, first, 0, SLIDE0_WORDS)
    assert [p["text"] for p in _parts(s)] == [SLIDE0_EDITED, SLIDE1_TAKE1]
    before = {p["id"]: p for p in _parts(s)}

    receipt = _take_two(s, monkeypatch, [(0, SLIDE0_TAKE2)])
    assert receipt["review_finalized"] is True and receipt["version"] == 2

    # THE SPOKEN SLIDE IS WHAT WAS SAID IN TAKE 2 (contract 8, 9): the owner
    # edit is replaced by Take 2's words, on the same Paragraph.
    after = _parts(s)
    assert [p["id"] for p in after] == [first, second]
    assert after[0]["text"] == SLIDE0_TAKE2
    row = _rows(s["conn"], "SELECT auto_text, version FROM coach_arc_ideal_text "
                           "WHERE arc_id=%s", (s["arc"],))[0]
    assert row == {"auto_text": f"{SLIDE0_TAKE2}\n\n{SLIDE1_TAKE1}", "version": 2}

    # THE UNSPOKEN SLIDE KEEPS ITS LAST VERSION (N29): same Paragraph, same
    # words, same lock, and no Take 2 revision appended to it.
    assert after[1]["text"] == SLIDE1_TAKE1
    assert after[1]["locked_at"] == before[second]["locked_at"]
    assert after[1]["root_phrase"] == SLIDE1_WORDS
    assert "take_rewrite" not in [r["action"] for r in _rows(
        s["conn"], "SELECT action FROM ideal_text_part_revision WHERE part_id=%s",
        (second,))]

    # LOCKED HELPER WORDS PERSIST (contract 14), on both Slides, though Take
    # 2's words on Slide 0 no longer contain them; the lock rides along.
    assert after[0]["root_phrase"] == SLIDE0_WORDS
    assert after[0]["locked_at"] == before[first]["locked_at"]
    slide_words = {(r["slide_index"], r["phrase"], r["locked_at"] is not None)
                   for r in s["db"].get_slide_helper_words(s["arc"], s["owner"])}
    assert slide_words == {(0, SLIDE0_WORDS, True), (1, SLIDE1_WORDS, True)}

    # NOTHING IS LOST (contract 9, 16): the edited words stay in the
    # Paragraph's immutable revision chain, under the Take 2 rewrite that
    # replaced them; the owner edit stays at its version (`prior_edit`); and
    # both document versions are kept.
    chain = _rows(s["conn"], """SELECT action, text, take_session_id::text take,
            review_version FROM ideal_text_part_revision
        WHERE arc_id=%s AND part_id=%s ORDER BY id""", (s["arc"], first))
    edited = [r for r in chain if r["action"] == "owner_part_text_updated"]
    assert [r["text"] for r in edited] == [SLIDE0_EDITED]
    assert chain[-1] == {"action": "take_rewrite", "text": SLIDE0_TAKE2,
                         "take": s["take2"], "review_version": 2}
    assert chain.index(edited[0]) < len(chain) - 1
    prior_edit = s["db"].get_user_ideal_edit(s["arc"], s["owner"])
    assert (prior_edit["text"], prior_edit["version"]) == (
        f"{SLIDE0_EDITED}\n\n{SLIDE1_TAKE1}", 1)
    versions = _rows(s["conn"], "SELECT version, text FROM ideal_text_versions "
                                "WHERE arc_id=%s ORDER BY version", (s["arc"],))
    assert versions == [
        {"version": 1, "text": f"{SLIDE0_TAKE1}\n\n{SLIDE1_TAKE1}"},
        {"version": 2, "text": f"{SLIDE0_TAKE2}\n\n{SLIDE1_TAKE1}"},
    ]


SLIDE1_EDITED = "Nobody believed the numbers until they saw them twice."


@pytest.mark.xfail(strict=True, reason=(
    "OPEN (found by this suite, 2026-10-05): `merge_by_slide` takes an "
    "unspoken Slide's words from `coach_arc_ideal_text.auto_text`, the "
    "machine's Take 1 text, so an owner edit on a Slide Take 2 did not "
    "speak is reverted to Take 1's words (the edit survives only in the "
    "revision chain and as `prior_edit`). Contract 8 / N29 says that Slide "
    "keeps its last version; whether Q5 A means otherwise is the founder's "
    "call. Strict: this flips to a failure the day the rebuild keeps it."))
def test_an_edit_on_a_slide_take_two_did_not_speak_is_its_last_version(
        speaker, monkeypatch):
    """N29: a Slide the speaker did not speak keeps its LAST version. When
    the owner edited it after Take 1, that edit is its last version."""
    s = speaker
    first, second = _take_one_paragraphs(s)
    _edit(s, [(first, SLIDE0_TAKE1), (second, SLIDE1_EDITED)])

    _take_two(s, monkeypatch, [(0, SLIDE0_TAKE2)])

    after = _parts(s)
    assert [p["id"] for p in after] == [first, second]
    assert after[0]["text"] == SLIDE0_TAKE2
    assert after[1]["text"] == SLIDE1_EDITED
