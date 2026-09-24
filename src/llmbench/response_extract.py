from __future__ import annotations
from typing import Any


def _clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or text == "[DONE]":
        return None
    return text


def _structured_text(value: Any) -> str | None:
    if not isinstance(value, list):
        return None
    parts = []
    for item in value:
        if not isinstance(item, dict):
            continue
        text = _clean_text(item.get("text"))
        if text:
            parts.append(text)
        elif item.get("type") in ("output_text", "text"):
            nested = _clean_text(item.get("content"))
            if nested:
                parts.append(nested)
    return "\n".join(parts) if parts else None


def extract_text_response(payload: dict) -> str | None:
    if not isinstance(payload, dict):
        return None
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0] if isinstance(choices[0], dict) else {}
        message = first.get("message") if isinstance(first, dict) else None
        if isinstance(message, dict):
            content = message.get("content")
            text = _clean_text(content) or _structured_text(content)
            if text:
                return text
            text = _clean_text(message.get("reasoning_content"))
            if text:
                return text
        text = _clean_text(first.get("text")) if isinstance(first, dict) else None
        if text:
            return text
    text = _clean_text(payload.get("output_text"))
    if text:
        return text
    output = payload.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            text = _clean_text(item.get("text")) or _clean_text(item.get("output_text"))
            if text:
                return text
            text = _structured_text(item.get("content"))
            if text:
                return text
    return None
