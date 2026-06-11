#!/bin/sh
# Railway web entrypoint.
#
# Two responsibilities besides booting gunicorn:
#   1. Locate ffmpeg (Nixpacks installs it via either Nix or apt; the runtime
#      PATH often omits both locations) and pin it via FFMPEG_PATH so the
#      Python audio pipeline doesn't silently fall back to imageio-ffmpeg.
#   2. Configure a long worker timeout for big multipart uploads.

# ── Locate ffmpeg ──────────────────────────────────────────────────────
# Probe every plausible install path. First match wins.
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

# Fall back to whatever `command -v ffmpeg` resolves to.
if [ -z "$FFMPEG_FOUND" ]; then
  FFMPEG_FOUND="$(command -v ffmpeg 2>/dev/null || true)"
fi

if [ -n "$FFMPEG_FOUND" ]; then
  export FFMPEG_PATH="$FFMPEG_FOUND"
  # Also prepend the directory to PATH so any subprocess that calls
  # `shutil.which("ffmpeg")` finds the same binary.
  export PATH="$(dirname "$FFMPEG_FOUND"):${PATH}"
  echo "[startup] ffmpeg located at $FFMPEG_FOUND"
else
  # Always include the common Nix profile dirs so imageio-ffmpeg's
  # fallback isn't the only option if Nix arrives later in the boot.
  export PATH="${HOME}/.nix-profile/bin:/root/.nix-profile/bin:/nix/var/nix/profiles/default/bin:${PATH}"
  echo "[startup] WARNING: no system ffmpeg found — Python will fall back to imageio-ffmpeg"
fi

# ── Boot gunicorn ──────────────────────────────────────────────────────
# Large multipart uploads (reference videos up to MAX_REFERENCE_VIDEO_SIZE_MB)
# need a long worker timeout. Override with GUNICORN_TIMEOUT (seconds),
# e.g. 1800 for 30 minutes.
#
# --config gunicorn_conf.py wires the post_worker_init librosa warmup
# (BE contract §4.1/§5.12): each worker pays the ~27s numba JIT at boot,
# before accepting traffic, so the first snippet-processing request after
# a deploy can't eat the cold-start and 502 on Railway's 15s proxy
# timeout. CLI flags below take precedence over the same keys in the file.
GUNICORN_TIMEOUT="${GUNICORN_TIMEOUT:-1800}"
exec gunicorn app:app \
  --config gunicorn_conf.py \
  --bind "0.0.0.0:${PORT}" \
  --workers 2 \
  --timeout "${GUNICORN_TIMEOUT}"
