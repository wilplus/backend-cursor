"""Typed state passed between the recording pipeline's domain stages.

The pipeline is being extracted incrementally.  This object starts with the
inputs and transcription outputs needed by the first stage; later stages can
add fields without turning the orchestrator back into a bag of unrelated local
variables.  The dataclass is frozen so a stage must return a new state instead
of changing another stage's state behind its back.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class RecordingState:
    """One recording's durable context plus derived pipeline state."""

    session_id: str
    user_id: Optional[str]
    recording_id: str
    audio_bytes: bytes
    filename: str
    session_context: Optional[dict]
    parent_audio_url: str
    recording_kind: str
    paired_session_id: Optional[str]
    run_analytics: bool
    signal: Any = None
    segments: tuple[Any, ...] = field(default_factory=tuple)
    words_all: tuple[Any, ...] = field(default_factory=tuple)
