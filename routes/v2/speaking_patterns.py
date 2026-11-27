"""The founder's one pattern library for owned Takes and blind corpus clips."""
from flask import request

from routes.admin import require_founder
from routes.v2.blueprint import v2_bp
from routes.v2.common import _is_valid_uuid
from routes.v2.processing_authorization import phase1_provider_route
from routes.v2.speaking_calibration import _json, _moment
from services import acted_examples, speaking_patterns
from services.rate_limits import whisper_limit
from services.corpus_coach_queue import queued_corpus_clip
from services.db import db
from services.refusal import Refusal

_ROOT = "/user/speaking-patterns"


def _unavailable():
    return Refusal("NOT_FOUND", "This moment is unavailable.", 404)


def _source_moment(source, session, snippet):
    if source == "take":
        return _moment(session, snippet)[1]
    if source != "corpus" or not all(map(_is_valid_uuid, (session, snippet))):
        raise _unavailable()
    clip, imported = queued_corpus_clip(db, snippet)
    # The founder's own acted recording (N708): labelled as a corpus clip.
    if not clip and (acted := acted_examples.acted_clip(db, str(request.user_id), session, snippet)):
        return acted
    if (not clip or str(imported["id"]) != session or
            (imported.get("intake_context") or {}).get("archived_at") or
            type(clip.get("duration_ms")) is not int or clip["duration_ms"] <= 0):
        raise _unavailable()

    from routes.v2.coach import _rater_language_outcome
    outcome, _ = _rater_language_outcome(imported, [clip])
    if outcome != "matched":
        raise _unavailable()
    return clip


@v2_bp.route(_ROOT, methods=["GET"])
@require_founder
def v2_speaking_pattern_library():
    offset = min(1_000_000, max(0, request.args.get("offset", 0, type=int)))
    rows = speaking_patterns.page(
        db, str(request.user_id), offset,
        kind=request.args.get("kind"), source=request.args.get("source"),
        search=request.args.get("q", "").strip()[:100],
    )
    eligibility = {}
    for row in rows:
        key = (row["source"], row["session_id"], row["snippet_id"])
        if key not in eligibility:
            try:
                _source_moment(*key)
                eligibility[key] = True
            except Refusal:
                eligibility[key] = False
    return _json({
        "examples": [row for row in rows if eligibility[row["source"], row["session_id"], row["snippet_id"]]],
        "next_offset": offset + len(rows) if len(rows) == speaking_patterns.PAGE_SIZE else None,
    })


@v2_bp.route(_ROOT + "/acted", methods=["GET"])
@require_founder
def v2_speaking_pattern_acted_list():
    """Act it (N708): the founder's acted recordings, and the names used."""
    return _json(acted_examples.listing(db, str(request.user_id)))


@v2_bp.route(_ROOT + "/acted", methods=["POST"])
@require_founder
@whisper_limit
def v2_speaking_pattern_acted_record():
    """Act it (N708): one acted recording (multipart: audio_file, state,
    pattern, language). The corpus import lane writes it out (202) through
    the processing-authorization path; GET shows it once ready."""
    try:
        return _json(*acted_examples.start(
            db, str(request.user_id), request.files.get("audio_file"), request.form))
    except Refusal as error:
        return _json(error.body, error.status)


@v2_bp.route(_ROOT + "/golden", methods=["GET"])
@require_founder
def v2_speaking_pattern_golden():
    """Your labels against what both pickers served (N702): a report only."""
    from services import picker_golden
    return _json(picker_golden.report(db, str(request.user_id)))


@v2_bp.route(_ROOT + "/<source>/<session>/<snippet>/words", methods=["GET"])
@require_founder
def v2_speaking_pattern_words(source, session, snippet):
    """The clip's own words, for Sniper's pause places (N705)."""
    try:
        clip = _source_moment(source, session, snippet)
    except Refusal as error:
        return _json(error.body, error.status)
    return _json({"words": speaking_patterns.clip_words(clip)})


@v2_bp.route(_ROOT + "/<source>/<session>/<snippet>/rewrite", methods=["GET"])
@require_founder
@phase1_provider_route
def v2_speaking_pattern_rewrite(source, session, snippet):
    """The clip's words and the app's better wording (N705): the one kept
    with the clip, else one made now (one provider call, nothing stored)."""
    try:
        clip = _source_moment(source, session, snippet)
    except Refusal as error:
        return _json(error.body, error.status)
    return _json({"words": speaking_patterns.clip_words(clip),
                  "rewrite": speaking_patterns.rewrite_for(clip)})


@v2_bp.route(_ROOT + "/<source>/<session>/<snippet>", methods=["GET", "POST", "PUT", "DELETE"])
@require_founder
def v2_speaking_pattern_examples(source, session, snippet):
    curator = str(request.user_id)
    try:
        clip = _source_moment(source, session, snippet)
        if request.method == "POST":
            body = request.get_json(silent=True)
            if not isinstance(body, dict):
                raise Refusal("INVALID_PATTERN", "Choose what you heard.", 400)
            speaking_patterns.save_observation(db, curator, source, session, clip, body)
        if request.method in ("PUT", "DELETE"):
            _change_match(curator, source, session, snippet)
        return _json(speaking_patterns.clip_examples(db, curator, source, session, clip))
    except Refusal as error:
        return _json(error.body, error.status)


def _change_match(curator, source, session, snippet):
    body = request.get_json(silent=True)
    example_id = body.get("example_id") if isinstance(body, dict) else None
    if not isinstance(example_id, str) or not _is_valid_uuid(example_id):
        raise _unavailable()
    fields = (curator, source, session, snippet, example_id)
    table = db.client.table(speaking_patterns.TABLE)
    rows = speaking_patterns.example_query(table.select("kind"), *fields).limit(1).execute().data
    if not rows:
        raise _unavailable()
    change = table.delete() if request.method == "DELETE" else table.update({
        "intervention": speaking_patterns.intervention(body, rows[0]["kind"]),
    })
    speaking_patterns.example_query(change, *fields).execute()
