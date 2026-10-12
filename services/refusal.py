"""One refusal type for the services a thin route calls.

A service raises ``Refusal(code, error, status)`` for a request it turns
down; the route answers ``jsonify(refusal.body), refusal.status``. The body
is exactly ``{"code", "error"}``, the shape every v2 refusal already has.
"""
from __future__ import annotations


class Refusal(Exception):
    """A refused request: the route answers ``body`` with ``status``."""

    def __init__(self, code: str, error: str, status: int) -> None:
        super().__init__(code)
        self.status = status
        self.body = {"code": code, "error": error}
