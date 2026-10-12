"""One refusal type for the services a thin route calls.

A service raises ``Refusal(code, error, status)`` for a request it turns
down; the route answers ``jsonify(refusal.body), refusal.status``. The body
is ``{"code", "error"}``, the shape every v2 refusal already has; a refusal
whose wire shape has no ``error`` passes ``error=None``, and any further
fields (``current_version``, ...) ride as keywords after it.
"""
from __future__ import annotations

from typing import Any, Optional


class Refusal(Exception):
    """A refused request: the route answers ``body`` with ``status``."""

    def __init__(self, code: str, error: Optional[str] = None,
                 status: int = 400, **extra: Any) -> None:
        super().__init__(code)
        self.status = status
        self.body: dict[str, Any] = {"code": code}
        if error is not None:
            self.body["error"] = error
        self.body.update(extra)
