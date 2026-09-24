from llmbench.capabilities import detect_capability, refine_capability_from_error
from llmbench.domain import ModelCapability


def test_model_id_heuristics_are_conservative_and_use_known_tokens():
    assert detect_capability("nvidia/nemotron-3-embed-1b", {}).capability is ModelCapability.EMBEDDING
    assert detect_capability("nvidia/nemotron-parse", {}).capability is ModelCapability.PARSER
    assert detect_capability("nvidia/riva-translate-4b", {}).capability is ModelCapability.TRANSLATION
    assert detect_capability("meta/llama-guard-4-12b", {}).capability is ModelCapability.SAFETY
    assert detect_capability("vendor/model-x", {}).capability is ModelCapability.UNKNOWN


def test_metadata_precedes_misleading_model_name():
    d = detect_capability("vendor/embed-looking-name", {"task": "text-generation"})
    assert d.capability is ModelCapability.CHAT_TEXT
    assert d.source == "metadata"
    assert d.confidence >= 0.9


def test_malformed_metadata_falls_back_without_crashing():
    d = detect_capability("vendor/model-x", {"task": ["unexpected"]})
    assert d.capability is ModelCapability.UNKNOWN


def test_metadata_embedding_and_vision_values_are_recognized():
    assert detect_capability("x", {"task": "embeddings"}).capability is ModelCapability.EMBEDDING
    assert detect_capability("x", {"pipeline_tag": "image-text-to-text"}).capability in {ModelCapability.VISION, ModelCapability.MULTIMODAL}


def test_text_input_mismatch_refines_to_non_chat_unknown_hint():
    d = refine_capability_from_error(ModelCapability.CHAT_TEXT, "Content cannot be a plain string. The model does not support text input.")
    assert d is not None
    assert d.capability is ModelCapability.UNKNOWN
    assert d.source == "probe"


def test_error_with_embedding_hint_can_refine_specifically():
    d = refine_capability_from_error(ModelCapability.CHAT_TEXT, "Use the embeddings endpoint for this embedding model")
    assert d is not None
    assert d.capability is ModelCapability.EMBEDDING


def test_generic_error_produces_no_refinement():
    assert refine_capability_from_error(ModelCapability.CHAT_TEXT, "internal server error") is None
