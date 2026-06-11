"""Gunicorn config — warms librosa's numba JIT before workers serve traffic.

Why this exists (willab BE contract §4.1 / §5.12, invariant):
``librosa.feature.mfcc`` triggers a one-time numba JIT compile on the
FIRST call per process — measured at ~27.3s cold, ~1ms warmed. Without
warming, the first real snippet-processing request after a deploy eats
that 27s and trips Railway's 15s proxy timeout → 502. That's the exact
outage pattern the contract names ("the same failure mode as the outage
~a week ago").

``post_worker_init`` runs inside each worker AFTER the app is loaded and
BEFORE the worker enters its request-serving loop, so the JIT cost is
paid at deploy time, per worker, never on a live request. With
``--workers 2`` the two workers warm in parallel (~27s wall, not 55s).
The existing ``--timeout 1800`` (set for big uploads in
bin/railway-web.sh) comfortably covers the warmup, so the master won't
reap a worker mid-compile.

Why not the "warmup line in railway-web.sh before exec gunicorn"
alternative: that runs in a separate Python process that exits before
gunicorn forks, so its in-memory numba JIT is gone and the workers boot
cold (numba's on-disk cache only covers functions decorated
``cache=True``, which librosa's internals don't all use). post_worker_init
warms the actual worker process — robust regardless of cache flags.

Best-effort: if librosa is unavailable or the warmup raises, we log and
continue. services/audio_metrics.py's librosa block is already
best-effort (try/except + import guard), so an unwarmed worker degrades
to a slow-first-call or absent-features, never a crash. The warmup is
an optimization against the 502, not a correctness dependency.
"""

# These two are read by gunicorn from this config file; bin/railway-web.sh
# also passes --workers/--timeout/--bind on the command line, which take
# precedence. Defined here only as documented fallbacks.
workers = 2
timeout = 1800


def post_worker_init(worker):
    """Pay librosa's numba JIT cost at worker boot, before traffic."""
    try:
        import numpy as np
        import librosa

        # Exercise the heavy shared numba path (STFT + mel filterbank)
        # via mfcc — the contract's prescribed warmup call. chroma_stft
        # is warmed too because services/audio_metrics.py calls it and
        # it pulls a distinct (chroma) filterbank; the remaining
        # features (spectral_centroid/rolloff, zcr, stft-based flux)
        # reuse the STFT core mfcc already compiled.
        y = np.zeros(16000, dtype="float32")
        librosa.feature.mfcc(y=y, sr=16000, n_mfcc=13)
        librosa.feature.chroma_stft(y=y, sr=16000)
        worker.log.info("[warmup] librosa numba JIT warmed (pid=%s)", worker.pid)
    except Exception as e:  # never block worker boot on the warmup
        worker.log.warning("[warmup] librosa warmup skipped: %s", e)
