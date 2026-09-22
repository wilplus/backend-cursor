#!/bin/sh
# Railway WORKER entrypoint (the durable recording-pipeline worker).
#
# Railway setup: New service → connect this repo → Settings:
#   Start Command: sh bin/railway-worker.sh
# Variables: same env group as the web service PLUS REDIS_URL (from the
# Railway Redis plugin) and PIPELINE_QUEUE_ENABLED=1.
#
# THE SAME ENTRYPOINT SERVES A SECOND, SIDE-LANE SERVICE (#596). An Ideal
# Text bake runs the whole Manager for twenty to forty seconds, and one
# queue used to serve everything — so a bake sat in the same line as a
# speaker's take. At one speaker that costs three seconds of queue wait
# (measured in processing_jobs); with several recording at once it would
# cost one person's take to warm another person's first open.
#
#   Bake service:  New service → same repo → Start Command as above, then
#                  WORKER_QUEUE=ideal-text-bakes   (this container's lane)
#                  WORKER_COUNT is ignored here — a side lane runs one slot
#   Web + worker:  BAKE_QUEUE_NAME=ideal-text-bakes  (where bakes are SENT)
#
# Both names must match. Unset, everything falls back to the pipeline queue
# and behaves exactly as it did before — so the variables can be set before
# or after this ships (CONFIG-FIRST), and a bake service that does not exist
# yet costs only the first open, never a bookmark.
#
# The side lane skips the librosa JIT and the pipeline sweeps: it decodes no
# audio. ffmpeg below is located anyway, because one entrypoint serving two
# roles is worth more than a branch that has to stay correct.
#
# Same ffmpeg-location dance as bin/railway-web.sh: Nixpacks installs
# ffmpeg via Nix or apt, the runtime PATH often omits both, and without
# FFMPEG_PATH the audio pipeline silently falls back to imageio-ffmpeg.

# ── The Phase-1 mode, before anything else can fail (B-1) ──────────────
# Unconditional and first: the case worth reporting is the container where
# this is MISSING, and a guarded echo is silent for exactly that one. The
# Python boot line (services/gate_flags.py) says it again with the rest of
# the gates — this one survives a boot that dies before the interpreter.
echo "[startup] PLF1_PROCESSING_AUTHORIZATION_MODE=${PLF1_PROCESSING_AUTHORIZATION_MODE:-(unset)}"

# ── Locate ffmpeg ──────────────────────────────────────────────────────
FFMPEG_FOUND=""
for candidate in \
  /usr/bin/ffmpeg \
  /usr/local/bin/ffmpeg \
  "${HOME}/.nix-profile/bin/ffmpeg" \
  /root/.nix-profile/bin/ffmpeg \
  /nix/var/nix/profiles/default/bin/ffmpeg; do
  if [ -x "$candidate" ]; then
    FFMPEG_FOUND="$candidate"
    break
  fi
done

if [ -z "$FFMPEG_FOUND" ]; then
  FFMPEG_FOUND="$(command -v ffmpeg 2>/dev/null || true)"
fi

# Last resort: the imageio-ffmpeg wheel bundles a real ffmpeg binary and is
# always installed (requirements.txt). Railway's Railpack builder does NOT
# read nixpacks.toml / apt.txt, so a service built with it has no system
# ffmpeg — resolve the bundled one EXPLICITLY here rather than leaving
# FFMPEG_PATH unset and letting each caller re-discover it. Pinning it also
# makes the log say which binary is actually in use.
if [ -z "$FFMPEG_FOUND" ]; then
  FFMPEG_FOUND="$(python3 -c 'import imageio_ffmpeg,sys; sys.stdout.write(imageio_ffmpeg.get_ffmpeg_exe())' 2>/dev/null || true)"
  if [ -n "$FFMPEG_FOUND" ]; then
    echo "[startup] no system ffmpeg — using the imageio-ffmpeg bundled binary"
  fi
fi

# ── Resolve the interpreter BEFORE touching PATH ───────────────────────
# Dependencies live in the build's virtualenv (/app/.venv under Railpack
# and Nixpacks alike). Under Railpack ffmpeg installs to /usr/bin, and
# PREPENDING that directory below would shadow the venv's python3 with the
# system interpreter — which has none of our packages, so the worker booted
# without sentry_sdk/supabase/rq and died in confusing ways. Pin the
# interpreter by absolute path here and the PATH order stops mattering.
if [ -n "$VIRTUAL_ENV" ] && [ -x "$VIRTUAL_ENV/bin/python" ]; then
  PYTHON="$VIRTUAL_ENV/bin/python"
elif [ -x /app/.venv/bin/python ]; then
  PYTHON=/app/.venv/bin/python
else
  PYTHON="$(command -v python3 || echo python3)"
fi
echo "[startup] python interpreter: $PYTHON"

if [ -n "$FFMPEG_FOUND" ]; then
  export FFMPEG_PATH="$FFMPEG_FOUND"
  # APPEND, never prepend: FFMPEG_PATH is what the audio pipeline actually
  # reads (services/audio_metrics.py checks it first), so PATH only needs to
  # let subprocesses resolve a bare `ffmpeg` — not worth shadowing the venv.
  export PATH="${PATH}:$(dirname "$FFMPEG_FOUND")"
  echo "[startup] ffmpeg located at $FFMPEG_FOUND"
else
  export PATH="${PATH}:${HOME}/.nix-profile/bin:/root/.nix-profile/bin:/nix/var/nix/profiles/default/bin"
  echo "[startup] WARNING: no ffmpeg found at all — audio decode will fail"
fi

# ── Boot the worker ────────────────────────────────────────────────────
exec "$PYTHON" worker.py
