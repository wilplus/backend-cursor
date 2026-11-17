"""Shared project-name validation and normalization."""
from __future__ import annotations

from typing import Any


PROJECT_NAME_MAX_LENGTH = 200
PROJECT_NAME_INVALID_MESSAGE = "display_name must be 1–200 characters"


def normalize_project_name(value: Any) -> str:
    """Apply the existing project display-name rule."""
    name = str(value or "").strip()
    if not name or len(name) > PROJECT_NAME_MAX_LENGTH:
        raise ValueError("invalid project name")
    return name
