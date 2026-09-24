from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Any

class ModelStatus(str, Enum):
    NEW="NEW"; ACTIVE="ACTIVE"; UNSTABLE="UNSTABLE"; FAILED="FAILED"; UNSUPPORTED="UNSUPPORTED"; DISABLED="DISABLED"; MISSING="MISSING"

class RunStatus(str, Enum):
    QUEUED="QUEUED"; RUNNING="RUNNING"; COMPLETED="COMPLETED"; COMPLETED_WITH_ERRORS="COMPLETED_WITH_ERRORS"; FAILED="FAILED"; CANCELLED="CANCELLED"

@dataclass(frozen=True)
class Provider:
    id:int; slug:str; name:str; provider_type:str; base_url:str; credential_source:str; credential_ref:str
    created_at:str; updated_at:str; last_discovery_at:str|None=None

@dataclass(frozen=True)
class ModelRecord:
    id:int; provider_id:int; model_id:str; status:ModelStatus; first_seen_at:str; last_seen_at:str
    last_success_at:str|None=None; last_failure_at:str|None=None; metadata:dict[str,Any]|None=None

@dataclass(frozen=True)
class BenchmarkRun:
    id:str; provider_id:int; mode:str; status:RunStatus; benchmark_profile:str
    started_at:str|None; finished_at:str|None; aiperf_version:str|None; requested_by:str|None; config:dict[str,Any]

@dataclass(frozen=True)
class DiscoveredModel:
    model_id:str
    metadata:dict[str,Any]

@dataclass(frozen=True)
class SmokeResult:
    ok:bool
    status_code:int|None=None
    error_type:str|None=None
    message:str|None=None
    retryable:bool=False
    content:str|None=None
    latency_ms:float|None=None
