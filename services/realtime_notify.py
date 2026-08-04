"""Best-effort Supabase Realtime broadcast for analysis-state flips.

The push half of the FE's push-first status transport (frontend-cursor #232 /
docs/BE-HANDOFF-analysis-state-push.md). One REST send per state flip, on a
broadcast channel whose NAME carries the session UUID — the same
unguessable-id capability trust model as the guest readout route, so nothing
is enumerable and no RLS changes. Payload is mechanical plumbing state ONLY
(AC-9 split-sink, same rule as routes/jobs.py): push says "state changed",
the existing readout GET serves the content.

MUST never raise and never block meaningfully: this fires inside the analysis
pipeline, the daemon and the CAS-guarded recovery sweeps. A lost broadcast
costs the FE latency (its poll fallback is the floor); a raised or slow one
would cost the live loop. Best-effort by contract, 2s hard timeout.
"""
from __future__ import annotations

import logging

import httpx

from config import Config

config = Config()
logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 2.0

# The FE builds against these verbatim (BE-HANDOFF-analysis-state-push §contract).
_TOPIC_PREFIX = "lab-session-"
_EVENT = "analysis_state"


def broadcast_analysis_state(session_id: str, state: str) -> None:
    """Announce one analysis_state flip. Fire-and-forget; swallows everything."""
    url = (getattr(config, "SUPABASE_URL", None) or "").rstrip("/")
    key = getattr(config, "SUPABASE_SERVICE_ROLE_KEY", None) or ""
    if not url or not key or not session_id:
        return
    try:
        httpx.post(
            f"{url}/realtime/v1/api/broadcast",
            headers={
                "apikey": key,
                "Authorization": f"Bearer {key}",
            },
            json={
                "messages": [
                    {
                        "topic": f"{_TOPIC_PREFIX}{session_id}",
                        "event": _EVENT,
                        # Plumbing state ONLY — never the readout, never
                        # scores/verdicts (AC-9). Adding a key here needs an
                        # FE ping + the handoff contract updated first.
                        "payload": {
                            "session_id": str(session_id),
                            "analysis_state": state,
                        },
                        "private": False,
                    }
                ]
            },
            timeout=_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.debug(
            "analysis-state broadcast skipped sid=%s state=%s",
            session_id, state,
        )
