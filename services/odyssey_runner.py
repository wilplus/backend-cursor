"""Private inference service. The calling worker owns authorization and storage."""
from __future__ import annotations

import hmac
import os
from pathlib import Path
from threading import Semaphore

from flask import Flask, request

from services import odyssey_model


def create_app(*, directory: Path | None = None, token: str | None = None) -> Flask:
    artifacts = directory or Path(os.environ["ODYSSEY_ARTIFACTS"])
    secret = (token or os.environ["ODYSSEY_RUNNER_TOKEN"]).encode()
    if len(secret) < 32:
        raise ValueError("Odyssey runner needs a service credential")
    # Warm once at startup; a missing or invalid model fails the readiness check.
    odyssey_model.load_model(artifacts)
    slot = Semaphore(1)
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = odyssey_model.MAX_WAV_BYTES

    @app.get("/health")
    def health():
        return {"model_version": odyssey_model.MODEL_VERSION}

    @app.post("/score")
    def score_clip():
        supplied = request.headers.get("Authorization", "").encode()
        if not hmac.compare_digest(supplied, b"Bearer " + secret):
            return {"error": "unauthorized"}, 401
        if request.mimetype != "audio/wav":
            return {"error": "expected_wav"}, 415
        if not slot.acquire(blocking=False):
            return {"error": "busy"}, 503, {"Retry-After": "1"}
        try:
            scores = odyssey_model.score(request.get_data(cache=False), artifacts)
        except odyssey_model.UnusableAudio:
            return {"error": "unusable_clip"}, 422
        finally:
            slot.release()
        return {"model_version": odyssey_model.MODEL_VERSION, "scores": scores}

    return app
