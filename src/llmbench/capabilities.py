from __future__ import annotations
from dataclasses import dataclass
import re
from typing import Any
from .domain import ModelCapability


@dataclass(frozen=True)
class CapabilityDetection:
    capability: ModelCapability
    source: str
    confidence: float


def _metadata_strings(metadata: dict[str, Any] | Any):
    if not isinstance(metadata, dict):
        return []
    values = []
    for key in ("task", "pipeline_tag", "capability", "type", "model_type", "endpoint_type"):
        value = metadata.get(key)
        if isinstance(value, str):
            values.append(value.lower().strip())
    return values


def _from_metadata(metadata: dict[str, Any] | Any) -> CapabilityDetection | None:
    for value in _metadata_strings(metadata):
        if any(x in value for x in ("text-generation", "text_generation", "chat-completion", "chat_completion", "causal-lm")):
            return CapabilityDetection(ModelCapability.CHAT_TEXT, "metadata", 1.0)
        if any(x in value for x in ("embedding", "embeddings", "feature-extraction", "sentence-similarity")):
            return CapabilityDetection(ModelCapability.EMBEDDING, "metadata", 1.0)
        if any(x in value for x in ("image-text-to-text", "visual-question", "vision-language", "multimodal")):
            return CapabilityDetection(ModelCapability.MULTIMODAL, "metadata", 0.95)
        if "translation" in value:
            return CapabilityDetection(ModelCapability.TRANSLATION, "metadata", 1.0)
        if "rerank" in value:
            return CapabilityDetection(ModelCapability.RERANK, "metadata", 1.0)
        if "safety" in value or "guard" in value:
            return CapabilityDetection(ModelCapability.SAFETY, "metadata", 0.95)
        if "parse" in value or "document" in value and "parse" in value:
            return CapabilityDetection(ModelCapability.PARSER, "metadata", 0.95)
    return None


def detect_capability(model_id: str, metadata: dict[str, Any] | Any) -> CapabilityDetection:
    detected = _from_metadata(metadata)
    if detected is not None:
        return detected

    text = (model_id or "").lower()
    tokens = set(re.findall(r"[a-z0-9]+", text))
    if tokens & {"embed", "embedding", "embedqa", "retriever", "nvclip", "clip"} or "embedqa" in text:
        return CapabilityDetection(ModelCapability.EMBEDDING, "model_id_heuristic", 0.8)
    if tokens & {"parse", "parser"} or "nemotron-parse" in text:
        return CapabilityDetection(ModelCapability.PARSER, "model_id_heuristic", 0.85)
    if tokens & {"translate", "translation"}:
        return CapabilityDetection(ModelCapability.TRANSLATION, "model_id_heuristic", 0.85)
    if tokens & {"guard", "safety"} or "content-safety" in text or "nemoguard" in text:
        return CapabilityDetection(ModelCapability.SAFETY, "model_id_heuristic", 0.8)
    if tokens & {"rerank", "reranker"}:
        return CapabilityDetection(ModelCapability.RERANK, "model_id_heuristic", 0.8)
    if tokens & {"vision", "vlm", "vila", "fuyu"}:
        return CapabilityDetection(ModelCapability.MULTIMODAL, "model_id_heuristic", 0.75)
    return CapabilityDetection(ModelCapability.UNKNOWN, "unknown", 0.0)


def refine_capability_from_error(current: ModelCapability | CapabilityDetection, message: str) -> CapabilityDetection | None:
    msg = (message or "").lower()
    if not msg:
        return None
    if "embedding" in msg or "embeddings endpoint" in msg:
        return CapabilityDetection(ModelCapability.EMBEDDING, "probe", 0.9)
    if any(x in msg for x in ("vision input", "image input", "multimodal")):
        return CapabilityDetection(ModelCapability.MULTIMODAL, "probe", 0.8)
    if "does not support text input" in msg or "content cannot be a plain string" in msg:
        return CapabilityDetection(ModelCapability.UNKNOWN, "probe", 0.6)
    return None
