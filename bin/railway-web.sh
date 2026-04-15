#!/bin/sh
# Nixpacks puts ffmpeg in the Nix user profile; the default web process PATH often omits it.
export PATH="${HOME}/.nix-profile/bin:/root/.nix-profile/bin:/nix/var/nix/profiles/default/bin:${PATH}"
# Large multipart uploads (reference videos up to MAX_REFERENCE_VIDEO_SIZE_MB) need a long worker timeout.
# Override with GUNICORN_TIMEOUT (seconds), e.g. 1800 for 30 minutes.
GUNICORN_TIMEOUT="${GUNICORN_TIMEOUT:-1800}"
exec gunicorn app:app --bind "0.0.0.0:${PORT}" --workers 2 --timeout "${GUNICORN_TIMEOUT}"
