#!/bin/sh
# Railway WORKER entrypoint (the durable recording-pipeline worker).
#
# Railway setup: New service → connect this repo → Settings:
#   Start Command: sh bin/railway-worker.sh
# Variables: same env group as the web service PLUS REDIS_URL (from the
# Railway Redis plugin) and PIPELINE_QUEUE_ENABLED=1.
#
# Same ffmpeg-location dance as bin/railway-web.sh: Nixpacks installs
# ffmpeg via Nix or apt, the runtime PATH often omits both, and without
# FFMPEG_PATH the audio pipeline silently falls back to imageio-ffmpeg.

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

if [ -n "$FFMPEG_FOUND" ]; then
  export FFMPEG_PATH="$FFMPEG_FOUND"
  export PATH="$(dirname "$FFMPEG_FOUND"):${PATH}"
  echo "[startup] ffmpeg located at $FFMPEG_FOUND"
else
  export PATH="${HOME}/.nix-profile/bin:/root/.nix-profile/bin:/nix/var/nix/profiles/default/bin:${PATH}"
  echo "[startup] WARNING: no system ffmpeg found — Python will fall back to imageio-ffmpeg"
fi

# ── Boot the worker ────────────────────────────────────────────────────
exec python3 worker.py
