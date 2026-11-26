"""Service-only prediction boundary for held-out baseline pilot recordings."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from services import experiment_baseline as pilot
from services.experiments import _data
from services.processing_authorization import ProcessingAuthorizationService

_PREDICTIONS = "experiment_baseline_predictions"
_SCORED = "experiment_baseline_scored"


@dataclass(frozen=True)
class Audio:
    content: bytes
    content_type: str


@dataclass(frozen=True)
class BlindInput:
    recording: Audio
    calibration: tuple[Audio, ...]


@dataclass(frozen=True)
class Prediction:
    valence: str | None
    energy: str | None


def _owner(database: Any, user_id: str) -> str:
    pilot.enabled(user_id)
    owner = pilot.volunteer(database, user_id)
    if not owner:
        raise pilot.error("PILOT_NOT_FOUND", 404)
    authority = ProcessingAuthorizationService(database)
    if authority.enforced:
        authority.require_current(authority.user_acquisition_principal(user_id), operation="ai_conversation")
    return owner


def _audio(row: dict) -> Audio:
    return Audio(bytes.fromhex(row["audio_hex"]), row["content_type"])


def _prediction(database: Any, step_id: str, model_version: str) -> dict | None:
    rows = _data(database.client.table(_PREDICTIONS).select("*")
                 .eq("step_id", step_id).eq("model_version", model_version).limit(1).execute())
    return rows[0] if rows else None


def predict_held_out(database: Any, *, user_id: str, run_id: str, step_id: str,
                     model_version: str, predictor: Callable[[BlindInput], Prediction]) -> dict:
    """Invoke a supplied predictor with audio only and persist its first result."""
    if not isinstance(model_version, str) or not 1 <= len(model_version.strip()) <= 120:
        raise pilot.error("PILOT_MODEL_VERSION", 422)
    model_version = model_version.strip()
    owner = _owner(database, user_id)
    rows = _data(database.client.rpc("blind_experiment_baseline_audio", {
        "p_volunteer_id": owner, "p_run_id": pilot._uuid(run_id), "p_step_id": pilot._uuid(step_id),
    }).execute())
    target = next((row for row in rows if row["target"]), None)
    if target is None:
        raise pilot.error("PILOT_HELD_OUT_REQUIRED", 404)
    step_id = target["step_id"]
    if stored := _prediction(database, step_id, model_version):
        return stored
    calibration = [row for row in rows if not row["target"]]
    if not calibration:
        raise pilot.error("PILOT_CALIBRATION_REQUIRED", 409)
    result = predictor(BlindInput(_audio(target), tuple(_audio(row) for row in calibration)))
    if (not isinstance(result, Prediction)
            or (result.valence is not None and result.valence not in pilot.VALENCES)
            or (result.energy is not None and result.energy not in pilot.ENERGIES)):
        raise pilot.error("PILOT_PREDICTION_INVALID", 422)
    database.client.table(_PREDICTIONS).upsert({
        "step_id": step_id, "model_version": model_version,
        "calibration_step_ids": [row["step_id"] for row in calibration],
        "predicted_valence": result.valence, "predicted_energy": result.energy,
    }, on_conflict="step_id,model_version", ignore_duplicates=True).execute()
    if stored := _prediction(database, step_id, model_version):
        return stored
    raise pilot.error("PILOT_STORE", 503)


def scored_prediction(database: Any, *, user_id: str, run_id: str, step_id: str,
                      model_version: str) -> dict | None:
    """Read the private comparison only after the matching prediction exists."""
    owner = _owner(database, user_id)
    rows = _data(database.client.table(_SCORED).select(
        "run_id,step_id,model_version,calibration_step_ids,predicted_valence,predicted_energy,"
        "predicted_at,felt_valence,felt_energy,intended_valence,intended_energy,prompt_id"
    ).eq("volunteer_id", owner).eq("run_id", pilot._uuid(run_id)).eq("step_id", pilot._uuid(step_id))
                 .eq("model_version", model_version.strip()).limit(1).execute())
    return rows[0] if rows else None
