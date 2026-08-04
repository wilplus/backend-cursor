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

# ── Optional migration step (OFF by default) ───────────────────────────
# The supported place to run migrations is bin/railway-migrate.sh as a
# Railway pre-deploy command — it runs to completion before traffic moves to
# the new deployment, and a failure stops the deploy.
#
# This hook exists for environments where a pre-deploy command isn't
# available. It is opt-in (MIGRATE_ON_BOOT=1) and deliberately CANNOT fail
# the boot: CLAUDE.md's live-loop constraint means a bad migration must
# degrade to "the schema change didn't land", never to a crash-looping web
# service. Every failure path here logs loudly and falls through to gunicorn.
if [ "$MIGRATE_ON_BOOT" = "1" ]; then
  echo "[startup] MIGRATE_ON_BOOT=1 — applying pending migrations"
  MIGRATION_ACTOR="${MIGRATION_ACTOR:-railway-boot}"
  export MIGRATION_ACTOR
  python3 scripts/migrate.py apply
  MIGRATE_STATUS=$?
  if [ "$MIGRATE_STATUS" -eq 0 ]; then
    echo "[startup] migrations up to date"
  else
    # Intentionally swallowed. Surfaced in logs and in `migrate.py status`.
    echo "[startup] WARNING: migrations did not complete (exit $MIGRATE_STATUS) — booting anyway."
    echo "[startup] Run 'python3 scripts/migrate.py status' to see what is pending."
  fi
fi

# ── RLS guard ──────────────────────────────────────────────────────────
# Reports public tables without RLS and public functions anon can EXECUTE.
# See scripts/rls_guard.py for why this is a deploy-time assertion and not a
# cron, and docs/RLS-AUDIT.md for what it is guarding against.
#
# DEFAULT ON, unlike MIGRATE_ON_BOOT above, and the difference is deliberate:
# that hook WRITES (a bad migration is a real risk, so it is opt-in), this one
# only READS two catalog queries in ~10ms. An opt-in security check that nobody
# opts into is precisely the "specified and never wired" failure this repo
# keeps writing about — so the default has to be on.
#
# Set RLS_GUARD=0 to skip. It cannot fail the boot: --strict is never passed,
# the script swallows its own exceptions, and `|| true` covers the rest.
if [ "$RLS_GUARD" != "0" ]; then
  python3 scripts/rls_guard.py || true
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
