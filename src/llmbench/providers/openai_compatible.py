from __future__ import annotations
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import httpx
from ..domain import DiscoveredModel, SmokeResult, ModelCapability
from ..classification import classify_http_error
from ..response_extract import extract_text_response


def normalize_error(status_code: int | None, message: str = ""):
    c = classify_http_error(status_code, message)
    return c.error_type, c.retryable


def _retry_after_seconds(response: httpx.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        value = float(raw)
        return value if value >= 0 else None
    except ValueError:
        try:
            when = parsedate_to_datetime(raw)
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


class OpenAICompatibleProvider:
    def __init__(self, base_url: str, client: httpx.Client | None = None, timeout: float = 30.0):
        self.base_url = base_url.rstrip('/')
        self.client = client or httpx.Client(timeout=timeout)

    def _v1(self):
        return self.base_url if self.base_url.endswith('/v1') else self.base_url + '/v1'

    def _headers(self, key):
        return {'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'}

    def discover_models(self, api_key: str):
        try:
            r = self.client.get(self._v1() + '/models', headers=self._headers(api_key))
        except httpx.TimeoutException as e:
            raise RuntimeError('TIMEOUT: model discovery failed') from e
        except httpx.RequestError as e:
            raise RuntimeError('NETWORK_ERROR: model discovery failed') from e
        if r.status_code >= 400:
            kind, _ = normalize_error(r.status_code, r.text)
            raise RuntimeError(f'{kind}: model discovery failed ({r.status_code})')
        payload = r.json()
        data = payload.get('data', payload.get('models', []))
        out = []
        for item in data:
            if isinstance(item, str):
                out.append(DiscoveredModel(item, {}))
            elif isinstance(item, dict) and item.get('id'):
                out.append(DiscoveredModel(str(item['id']), {k: v for k, v in item.items() if k != 'id'}))
        return out

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        try:
            body = response.json()
        except Exception:
            return response.text
        if not isinstance(body, dict):
            return response.text
        error = body.get('error')
        if isinstance(error, dict) and error.get('message'):
            return str(error['message'])
        if isinstance(error, str):
            return error
        for key in ('detail', 'message', 'title'):
            if body.get(key):
                return str(body[key])
        return response.text

    def _probe_chat(self, model_id: str, api_key: str, prompt='Say hello.', extra=None, max_tokens=16, streaming=False):
        payload = {'model': model_id, 'messages': [{'role': 'user', 'content': prompt}], 'max_tokens': max_tokens, 'stream': streaming}
        if extra:
            payload.update(extra)
        t = time.perf_counter()
        try:
            r = self.client.post(self._v1() + '/chat/completions', headers=self._headers(api_key), json=payload)
        except httpx.TimeoutException:
            return SmokeResult(False, None, 'TIMEOUT', 'request timed out', True, latency_ms=(time.perf_counter()-t)*1000)
        except httpx.RequestError as e:
            return SmokeResult(False, None, 'NETWORK_ERROR', str(e), True, latency_ms=(time.perf_counter()-t)*1000)
        latency = (time.perf_counter()-t)*1000
        if r.status_code >= 400:
            msg = self._error_message(r)
            c = classify_http_error(r.status_code, msg)
            return SmokeResult(False, r.status_code, c.error_type, msg, c.retryable, latency_ms=latency, retry_after_seconds=_retry_after_seconds(r))
        try:
            body = r.json()
        except Exception as e:
            return SmokeResult(False, r.status_code, 'INVALID_RESPONSE', str(e), False, latency_ms=latency)
        content = extract_text_response(body)
        if not content:
            return SmokeResult(False, r.status_code, 'EMPTY_RESPONSE', 'response contained no recognized content', False, latency_ms=latency)
        return SmokeResult(True, r.status_code, content=content, latency_ms=latency)

    def _probe_embedding(self, model_id: str, api_key: str):
        t = time.perf_counter()
        try:
            r = self.client.post(self._v1() + '/embeddings', headers=self._headers(api_key), json={'model': model_id, 'input': 'hello'})
        except httpx.TimeoutException:
            return SmokeResult(False, None, 'TIMEOUT', 'request timed out', True, latency_ms=(time.perf_counter()-t)*1000)
        except httpx.RequestError as e:
            return SmokeResult(False, None, 'NETWORK_ERROR', str(e), True, latency_ms=(time.perf_counter()-t)*1000)
        latency = (time.perf_counter()-t)*1000
        if r.status_code >= 400:
            msg = self._error_message(r)
            c = classify_http_error(r.status_code, msg)
            return SmokeResult(False, r.status_code, c.error_type, msg, c.retryable, latency_ms=latency, retry_after_seconds=_retry_after_seconds(r))
        try:
            body = r.json()
            data = body.get('data', []) if isinstance(body, dict) else []
            vector = data[0].get('embedding') if data and isinstance(data[0], dict) else None
            valid = isinstance(vector, list) and bool(vector) and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vector)
        except Exception:
            valid = False
        if not valid:
            return SmokeResult(False, r.status_code, 'INVALID_RESPONSE', 'embedding response contained no numeric vector', False, latency_ms=latency)
        return SmokeResult(True, r.status_code, content=f'embedding[{len(vector)}]', latency_ms=latency)

    def probe(self, model_id: str, api_key: str, capability: ModelCapability) -> SmokeResult:
        if capability is ModelCapability.EMBEDDING:
            return self._probe_embedding(model_id, api_key)
        if capability in (ModelCapability.CHAT_TEXT, ModelCapability.UNKNOWN):
            return self._probe_chat(model_id, api_key)
        return SmokeResult(False, None, 'UNSUPPORTED', f'no generic probe for capability {capability.value}', False)

    def benchmark_profile_for(self, capability: ModelCapability) -> str | None:
        return 'baseline-v1' if capability is ModelCapability.CHAT_TEXT else None

    def smoke_test(self, model_id: str, api_key: str, prompt='Say hello.', extra=None, max_tokens=16, streaming=False):
        if prompt == 'Say hello.' and extra is None and max_tokens == 16 and streaming is False:
            return self.probe(model_id, api_key, ModelCapability.CHAT_TEXT)
        return self._probe_chat(model_id, api_key, prompt=prompt, extra=extra, max_tokens=max_tokens, streaming=streaming)
