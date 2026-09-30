"""The MLC-3 exercise service loop's coach-side blind review — RETIRED.

Founder 2026-09-30 (L8; contract 66): the coach half of the service loop
(blind playback, source playback, inline render and judgment, review sets
and their completion — eight routes under ``/v2/coach/mlc3/...``) is retired
with the loop. Every path under that prefix is one 410 tombstone, the way
``routes/v2/arcs.py`` (``v2_arc_unlock``) and ``routes/phase2_guard.py``
retire a door. The tables stay; the coach corpus queue never hands out an
MLC-3 inline blind assignment again (``routes/v2/coach.py``,
``_inline_authoring_for``). The module keeps its name and its place in
``DOMAIN_MODULES`` so the blueprint registers exactly as before.
"""
from __future__ import annotations

from flask import jsonify

from routes.v2.blueprint import v2_bp

GONE_ERROR = (
    "The MLC-3 service loop was retired (founder 2026-09-30, L8; contract 66)."
)


@v2_bp.route(
    "/coach/mlc3/<path:rest>", methods=["GET", "POST", "PUT", "DELETE"],
)
def v2_mlc3_coach_review_retired(rest: str):
    """410 GONE for every retired ``/v2/coach/mlc3/...`` path."""
    return jsonify({"code": "GONE", "error": GONE_ERROR}), 410
