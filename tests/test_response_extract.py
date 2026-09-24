from llmbench.response_extract import extract_text_response


def test_extracts_supported_text_shapes():
    cases = [
        ({"choices":[{"message":{"content":"hello"}}]}, "hello"),
        ({"choices":[{"message":{"content":[{"type":"text","text":"hello"}]}}]}, "hello"),
        ({"choices":[{"message":{"reasoning_content":"hello"}}]}, "hello"),
        ({"choices":[{"text":"hello"}]}, "hello"),
        ({"output_text":"hello"}, "hello"),
    ]
    for payload, expected in cases:
        assert extract_text_response(payload) == expected


def test_usage_only_null_empty_and_done_are_not_success():
    cases = [
        {"usage":{"completion_tokens":1}},
        {"choices":[{"message":{"content":None}}]},
        {"choices":[{"message":{"content":[]}}]},
        {"choices":[{"message":{"content":""}}]},
        {"choices":[{"message":{"content":"[DONE]"}}]},
        {},
    ]
    for payload in cases:
        assert extract_text_response(payload) is None
