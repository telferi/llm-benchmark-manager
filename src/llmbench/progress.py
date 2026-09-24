from __future__ import annotations
from copy import deepcopy
from .domain import ModelCapability


def progress_event(snapshot: dict, model_id: str, stage: str, capability: ModelCapability, outcome: str | None = None) -> dict:
    event = deepcopy(snapshot)
    event["event"] = {
        "model_id": model_id,
        "stage": stage,
        "capability": capability.value,
        "outcome": outcome,
    }
    return event
