"""One line, at boot, naming every gate flag and the value it holds.

J1-4 (minor) and B-1 (major), audit 2026-09-22.

CONFIG-FIRST says to verify a per-service variable from that service's BOOT
LOG rather than the Railway panel, because the panel shows what somebody
typed and the log shows what the process READ. For these flags that rule was
unfollowable: not one of them was printed anywhere, by any service. The
deployed value of `PLF1_PROCESSING_AUTHORIZATION_MODE` was derivable only
for the web container, which exposes it on a route; the worker and the crons
had no observable surface at all (B-1).

That matters most for the worker, which is the container that WRITES the
lineage. The worst case CONFIG-FIRST names is a writer service missing a
variable: the web app looks healthy while background jobs silently drop what
they should be recording. #614 learned this for the stored bookmark set on
the same day, one flag family over, and gave it a contract test. This is the
same lesson applied to the gates.

READ AT CALL TIME, NOT AT IMPORT, AND THROUGH `Config`. Every attribute on
`Config` resolves once when that module is first imported, which in a worker
is long before most of the process exists — so this asks `Config.current_env`
for the values as they stand when the line is emitted. It goes through
`Config` rather than reading `os.environ` here because `os.environ` is read
in `config.py` and `services/secrets.py` and nowhere else (audit Q-A5,
`tests/test_config_reads_fence.py`). A boot line about configuration
discipline is the last place to make an exception to it.

NOTHING HERE PRINTS A SECRET. Names and values only. A flag whose value
identifies a person goes in IDENTIFYING_FLAGS and is reported as `set` or
`unset`, never by id — a deploy log is not a place to put one.
"""
from __future__ import annotations

#: The flags that decide what is served, what is recorded, and who is bound.
#: Order is deliberate: the Phase-1 boundary first, because it is the one
#: whose value cannot be discovered any other way on the worker.
GATE_FLAGS: tuple[str, ...] = (
    "PLF1_PROCESSING_AUTHORIZATION_MODE",
    "TAKE_FEEDBACK_POLICY_V3_MODE",
    "MLC3_SERVICE_ENABLED",
    "MLC3_COACH_INLINE_AUTHORING_ENABLED",
    "CONFIDENT_MOMENT_BUNDLE_V1_ENABLED",
    "MLC2_CONFIDENCE_MONITORING_ENABLED",
    # Last, and the one this line matters most for after the Phase-1 boundary:
    # it decides which Confident Voice item is SELECTED, and the selection is
    # then FROZEN with the Take. Two services holding different values do not
    # produce an error or a degraded response — they produce two well-formed
    # items, one frozen and the other served, with nothing anywhere saying
    # they disagreed (contract 24j).
    "REASONABLE_CONFIDENCE_ENABLED",
    # The three switches that choose which F1 code path runs (audit A2,
    # 2026-09-28). LIVING_TRANSCRIPT_ENABLED defaults OFF in code but is on
    # in production: a service that never got the variable silently takes
    # the retired provenance lane and serves no Feedback. "(unset)" here is
    # that service. The default is flipped only once every service's boot
    # line shows it set (remediation C5).
    "LIVING_TRANSCRIPT_ENABLED",
    "IDEAL_TEXT_FEEDBACK_BAKE_ENABLED",
    "PIPELINE_QUEUE_ENABLED",
)

#: Reported as set/unset, never by value. Extend this rather than adding a
#: flag to GATE_FLAGS whenever the value identifies a person. Empty since
#: 2026-09-29: the canary principal variable it held was retired with the
#: rings (0394); who a feature reaches is a row, not a variable.
IDENTIFYING_FLAGS: tuple[str, ...] = ()

_UNSET = "(unset)"


def gate_summary() -> str:
    """One line: every gate flag, and the value this process read.

    One line rather than one per flag, so a single log filter answers the
    question on any service instead of a search that has to be run twice.
    """
    from config import Config

    values = Config.current_env([*GATE_FLAGS, *IDENTIFYING_FLAGS])
    parts = [f"{name}={values[name] or _UNSET}" for name in GATE_FLAGS]
    parts += [
        f"{name}={'set' if values[name] else 'unset'}"
        for name in IDENTIFYING_FLAGS
    ]
    return " ".join(parts)
