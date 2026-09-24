from __future__ import annotations
from pathlib import Path
from dataclasses import asdict
from typing import Callable
from urllib.parse import urlparse
import re
import time

from .db import Database
from .domain import ModelStatus, ModelCapability, RunStatus, Provider, SmokeResult
from .credentials import CredentialManager, sanitize_provider_message
from .discovery import DiscoveryService
from .providers.openai_compatible import OpenAICompatibleProvider
from .benchmark.aiperf import AIPerfRunner, AIPerfUnavailable, AIPerfError
from .benchmark.profiles import BASELINE_V1
from .capabilities import CapabilityDetection, detect_capability, refine_capability_from_error
from .classification import classify_http_error, retry_delays_for
from .progress import progress_event

RETRYABLE_HTTP = {429, 500, 502, 503, 504}


def _safe_component(value: str) -> str:
    out = ''.join(c if c.isalnum() or c in '-_.' else '_' for c in value)
    while '..' in out:
        out = out.replace('..', '_')
    return out[:180] or 'model'


class BenchmarkService:
    def __init__(self, db: Database, credential_resolver=None, adapter_factory=None, benchmark_runner=None,
                 artifact_root=None, stability_checks: int = 3, retry_delays=None, sleep_fn=None):
        self.db = db
        self.credentials = credential_resolver or CredentialManager()
        self.adapter_factory = adapter_factory or self._default_adapter
        self.benchmark_runner = benchmark_runner or AIPerfRunner()
        self.artifact_root = Path(artifact_root or Path.home() / '.local/share/llmbench/artifacts')
        self.stability_checks = max(0, int(stability_checks))
        self.retry_delays_override = None if retry_delays is None else tuple(retry_delays)
        self.sleep_fn = sleep_fn or time.sleep
        self.discovery_service = DiscoveryService(db)

    def _default_adapter(self, p: Provider):
        if p.provider_type not in ('openai-compatible', 'openai_compatible', 'openai'):
            raise ValueError(f'unsupported provider type: {p.provider_type}')
        return OpenAICompatibleProvider(p.base_url)

    def resolve_provider(self, value: int | str):
        if isinstance(value, int) or (isinstance(value, str) and value.isdigit()):
            return self.db.get_provider(int(value))
        return self.db.get_provider_by_slug(str(value))

    def _validated_url(self, base_url: str):
        u = urlparse(base_url)
        if u.scheme not in ('http', 'https') or not u.netloc or u.username or u.password:
            raise ValueError('provider URL must be http(s) and must not embed credentials')
        return u

    def _identity_from_url(self, base_url: str):
        u = self._validated_url(base_url)
        host = (u.hostname or '').lower()
        labels = [x for x in host.split('.') if x]
        generic = {'www', 'api', 'integrate', 'gateway', 'cloud', 'v1', 'com', 'net', 'org', 'io', 'ai', 'co', 'uk', 'dev'}
        candidates = [x for x in labels if x not in generic and not x.isdigit()]
        base = candidates[-1] if candidates else (labels[0] if labels else 'provider')
        slug = re.sub(r'[^a-z0-9]+', '-', base.lower()).strip('-') or 'provider'
        existing = {p.slug for p in self.db.list_providers()}
        unique = slug
        n = 2
        while unique in existing:
            unique = f'{slug}-{n}'
            n += 1
        return unique, base.replace('-', ' ').title()

    def add_provider(self, slug, name, provider_type, base_url, credential_env):
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', credential_env or ''):
            raise ValueError('invalid credential ENV variable name')
        self._validated_url(base_url)
        return self.db.add_provider(slug, name, provider_type, base_url, 'env', credential_env)

    def add_provider_with_secret(self, base_url, api_key, provider_type='openai-compatible'):
        if not api_key:
            raise ValueError('API key cannot be empty')
        self._validated_url(base_url)
        normalized = base_url.rstrip('/')
        existing = next((p for p in self.db.list_providers() if p.base_url.rstrip('/') == normalized), None)
        if existing is not None:
            ref = f'provider:{existing.slug}'
            source, stored_ref = self.credentials.store(ref, api_key)
            try:
                return self.db.update_provider_credential(existing.id, source, stored_ref)
            except Exception:
                self.credentials.delete(source, stored_ref)
                raise
        slug, name = self._identity_from_url(normalized)
        ref = f'provider:{slug}'
        source, stored_ref = self.credentials.store(ref, api_key)
        try:
            return self.db.add_provider(slug, name, provider_type, normalized, source, stored_ref)
        except Exception:
            self.credentials.delete(source, stored_ref)
            raise

    def list_providers(self):
        return self.db.list_providers()

    def provider_view(self, p: Provider):
        d = asdict(p)
        d['credential_available'] = self.credentials.availability(p.credential_ref, p.credential_source)
        return d

    def discover(self, provider: int | str):
        p = self.resolve_provider(provider)
        key = self.credentials.resolve(p.credential_ref, p.credential_source)
        adapter = self.adapter_factory(p)
        discovered = adapter.discover_models(key)
        result = self.discovery_service.reconcile(p.id, [x.model_id for x in discovered])
        for d in discovered:
            current = self.db.get_model(p.id, d.model_id)
            self.db.upsert_model(p.id, d.model_id, current.status, d.metadata)
        return result

    def select_models(self, provider: int | str, mode: str):
        p = self.resolve_provider(provider)
        models = self.db.list_models(p.id)
        mode = mode.lower()
        if mode == 'full':
            return [m for m in models if m.status not in (ModelStatus.DISABLED, ModelStatus.MISSING)]
        if mode == 'new':
            statuses = {ModelStatus.NEW}
        elif mode == 'active':
            statuses = {ModelStatus.ACTIVE}
        elif mode in ('unstable', 'unstable_failed'):
            statuses = {ModelStatus.UNSTABLE} if mode == 'unstable' else {ModelStatus.UNSTABLE, ModelStatus.FAILED}
        elif mode == 'failed':
            statuses = {ModelStatus.FAILED}
        else:
            raise ValueError(f'unknown run mode: {mode}')
        return [m for m in models if m.status in statuses]

    def create_run(self, provider: int | str, mode='full', requested_by='cli', profile='baseline-v1', model_id: str | None = None):
        p = self.resolve_provider(provider)
        config = {'model_id': model_id} if model_id else {}
        return self.db.create_run(p.id, mode, profile, requested_by, config=config)

    def run_progress(self, run_id: str) -> dict:
        snapshot = self.db.get_run_progress(run_id)
        run = self.db.get_run(run_id)
        by_status = {}
        valid_statuses = {status.value for status in ModelStatus}
        for row in snapshot['models']:
            status = row.get('final_status')
            if not status and row['stage'] == 'DONE' and row.get('outcome') in valid_statuses:
                status = row['outcome']
            if not status:
                status = self.db.get_model(run.provider_id, row['model_id']).status.value
            row['model_status'] = status
            if row['stage'] == 'DONE':
                by_status[status] = by_status.get(status, 0) + 1
        snapshot['by_status'] = by_status
        return snapshot

    def _emit(self, callback, run_id, model_id, stage, capability, outcome=None):
        if callback is not None:
            callback(progress_event(self.run_progress(run_id), model_id, stage, capability, outcome))

    def _record_smoke_error(self, run_id, model, result, secret=None):
        self.db.add_error(
            run_id,
            model.id,
            result.error_type or 'SMOKE_ERROR',
            sanitize_provider_message(result.message or '', (secret,)),
            result.status_code,
            1,
        )

    @staticmethod
    def _invoke_probe(adapter, model_id, key, capability):
        if hasattr(adapter, 'probe'):
            return adapter.probe(model_id, key, capability)
        return adapter.smoke_test(model_id, key)

    def _retry_schedule(self, result: SmokeResult):
        if not result.retryable:
            return ()
        base = self.retry_delays_override if self.retry_delays_override is not None else retry_delays_for(result.error_type or '')
        retry_after = getattr(result, 'retry_after_seconds', None)
        if (result.error_type or '').upper() == 'RATE_LIMITED' and retry_after is not None:
            safe = max(0.0, float(retry_after))
            return tuple(max(float(delay), safe) for delay in base)
        return tuple(base)

    def _probe_with_retry(self, adapter, model, key, capability, run_id, stage, callback):
        prior = []
        self.db.update_run_progress(run_id, model.id, stage=stage, capability=capability, attempt_increment=1)
        self._emit(callback, run_id, model.model_id, stage, capability)
        result = self._invoke_probe(adapter, model.model_id, key, capability)
        self._emit(callback, run_id, model.model_id, stage, capability, 'PASS' if result.ok else (result.error_type or 'FAIL'))
        for delay in self._retry_schedule(result):
            if result.ok or not result.retryable:
                break
            prior.append(result)
            self.sleep_fn(delay)
            self.db.update_run_progress(run_id, model.id, stage=stage, capability=capability, attempt_increment=1)
            self._emit(callback, run_id, model.model_id, stage, capability)
            result = self._invoke_probe(adapter, model.model_id, key, capability)
            self._emit(callback, run_id, model.model_id, stage, capability, 'PASS' if result.ok else (result.error_type or 'FAIL'))
        return result, prior

    @staticmethod
    def _failure_status(result: SmokeResult, capability: ModelCapability):
        if result.error_type == 'UNSUPPORTED':
            return ModelStatus.UNSUPPORTED
        c = classify_http_error(result.status_code, result.message or '')
        if result.error_type == 'MODEL_NOT_FOUND' or c.model_status is ModelStatus.NOT_AVAILABLE:
            return ModelStatus.NOT_AVAILABLE
        if result.error_type == 'CAPABILITY_MISMATCH' or c.model_status is ModelStatus.INCOMPATIBLE:
            return ModelStatus.INCOMPATIBLE
        if result.retryable:
            return ModelStatus.UNSTABLE
        if result.error_type == 'AUTH_ERROR' or c.error_type == 'AUTH_ERROR':
            return None
        if capability is ModelCapability.UNKNOWN:
            return ModelStatus.INCOMPATIBLE
        return ModelStatus.FAILED

    def _finish_model(self, run_id, model, status, capability, callback, *, outcome=None, diagnostic=None):
        if status is not None:
            self.db.set_model_status(model.id, status, diagnostic or 'run complete')
        final_outcome = outcome if outcome is not None else (status.value if status is not None else diagnostic)
        self.db.update_run_progress(run_id, model.id, stage='DONE', capability=capability, outcome=final_outcome, diagnostic_code=diagnostic, final_status=status, finished=True)
        self._emit(callback, run_id, model.model_id, 'DONE', capability, final_outcome)

    def _initial_detection(self, model):
        if model.capability is not ModelCapability.UNKNOWN or model.capability_source != 'unknown':
            return CapabilityDetection(model.capability, model.capability_source, model.capability_confidence)
        return detect_capability(model.model_id, model.metadata or {})

    def execute_run(self, run_id: str, cancel_check: Callable[[], bool] | None = None, progress_callback=None):
        cancelled = cancel_check or (lambda: False)
        run = self.db.get_run(run_id)
        p = self.db.get_provider(run.provider_id)
        self.db.update_run_status(run_id, RunStatus.RUNNING)
        try:
            key = self.credentials.resolve(p.credential_ref, p.credential_source)
            adapter = self.adapter_factory(p)
        except Exception:
            self.db.update_run_status(run_id, RunStatus.FAILED)
            raise

        had_errors = False
        aiperf_version = None
        models = self.select_models(p.id, run.mode)
        if run.config.get('model_id'):
            models = [m for m in models if m.model_id == run.config['model_id']]
        self.db.init_run_progress(run_id, models)

        for original in models:
            if cancelled():
                return self.db.update_run_status(run_id, RunStatus.CANCELLED)
            model = self.db.get_model_by_id(original.id)
            detection = self._initial_detection(model)
            capability = detection.capability
            self.db.set_model_capability(model.id, capability, detection.source, detection.confidence)
            self.db.update_run_progress(run_id, model.id, stage='CAPABILITY', capability=capability)
            self._emit(progress_callback, run_id, model.model_id, 'CAPABILITY', capability)

            try:
                smoke, retry_failures = self._probe_with_retry(adapter, model, key, capability, run_id, 'SMOKE', progress_callback)
            except Exception:
                self.db.update_run_status(run_id, RunStatus.FAILED)
                raise

            unstable = bool(retry_failures)
            for failure in retry_failures:
                had_errors = True
                self._record_smoke_error(run_id, model, failure, key)

            if not smoke.ok:
                had_errors = True
                self._record_smoke_error(run_id, model, smoke, key)
                status = self._failure_status(smoke, capability)
                if status is ModelStatus.INCOMPATIBLE:
                    refined = refine_capability_from_error(capability, smoke.message or '')
                    if refined is not None:
                        capability = refined.capability
                        self.db.set_model_capability(model.id, capability, refined.source, refined.confidence)
                if status is None:
                    self._finish_model(run_id, model, None, capability, progress_callback, outcome='AUTH_ERROR', diagnostic='AUTH_ERROR')
                    return self.db.update_run_status(run_id, RunStatus.FAILED, aiperf_version)
                self._finish_model(run_id, model, status, capability, progress_callback, diagnostic=smoke.error_type or 'smoke failure')
                continue

            if capability is ModelCapability.UNKNOWN:
                capability = ModelCapability.CHAT_TEXT
                self.db.set_model_capability(model.id, capability, 'probe', 0.9)
                self.db.update_run_progress(run_id, model.id, stage='SMOKE', capability=capability)

            definitive_status = None
            for _ in range(self.stability_checks):
                if cancelled():
                    return self.db.update_run_status(run_id, RunStatus.CANCELLED)
                check, retry_failures = self._probe_with_retry(adapter, model, key, capability, run_id, 'STABILITY', progress_callback)
                if retry_failures:
                    unstable = True
                    for failure in retry_failures:
                        had_errors = True
                        self._record_smoke_error(run_id, model, failure, key)
                if check.ok:
                    continue
                had_errors = True
                self._record_smoke_error(run_id, model, check, key)
                status = self._failure_status(check, capability)
                if check.retryable:
                    unstable = True
                    continue
                definitive_status = status or ModelStatus.FAILED
                break

            if definitive_status is not None:
                self._finish_model(run_id, model, definitive_status, capability, progress_callback, diagnostic='stability failure')
                continue

            profile_name = adapter.benchmark_profile_for(capability) if hasattr(adapter, 'benchmark_profile_for') else 'baseline-v1'
            self.db.update_run_progress(run_id, model.id, stage='BENCHMARK', capability=capability)
            self._emit(progress_callback, run_id, model.model_id, 'BENCHMARK', capability)
            if profile_name is None:
                self.db.set_model_status(model.id, ModelStatus.UNSTABLE if unstable else ModelStatus.ACTIVE, 'probe complete; no matching benchmark profile')
                self.db.update_run_progress(run_id, model.id, stage='BENCHMARK', capability=capability, outcome='SKIPPED_UNSUPPORTED_PROFILE', diagnostic_code='SKIPPED_UNSUPPORTED_PROFILE')
                self._finish_model(run_id, model, ModelStatus.UNSTABLE if unstable else ModelStatus.ACTIVE, capability, progress_callback, outcome='SKIPPED_UNSUPPORTED_PROFILE', diagnostic='SKIPPED_UNSUPPORTED_PROFILE')
                continue

            art = self.artifact_root / _safe_component(p.slug) / run_id / _safe_component(model.model_id)
            try:
                out = self.benchmark_runner.run(model_id=model.model_id, base_url=p.base_url, api_key=key, profile=BASELINE_V1, artifact_dir=art)
            except (AIPerfUnavailable, AIPerfError) as e:
                had_errors = True
                self.db.add_error(run_id, model.id, type(e).__name__, sanitize_provider_message(str(e), (key,)))
                self._finish_model(run_id, model, ModelStatus.UNSTABLE, capability, progress_callback, outcome='BENCHMARK_ERROR', diagnostic=type(e).__name__)
                continue
            except Exception:
                self.db.update_run_status(run_id, RunStatus.FAILED)
                raise

            aiperf_version = out.aiperf_version or aiperf_version
            self.db.add_result(run_id, model.id, success_count=out.success_count, error_count=out.error_count, metrics=out.metrics, raw_artifact_path=out.artifact_path)
            if out.error_count:
                unstable = True
                had_errors = True
            for err in out.errors:
                self.db.add_error(run_id, model.id, err.get('error_type', 'INFERENCE_ERROR'), sanitize_provider_message(err.get('message', ''), (key,)), err.get('http_status'), err.get('count', 1))
                if err.get('http_status') in RETRYABLE_HTTP:
                    unstable = True
            status = ModelStatus.UNSTABLE if unstable else ModelStatus.ACTIVE
            self._finish_model(run_id, model, status, capability, progress_callback, diagnostic='benchmark complete')

        status = RunStatus.COMPLETED_WITH_ERRORS if had_errors else RunStatus.COMPLETED
        return self.db.update_run_status(run_id, status, aiperf_version)

    def model_history(self, provider: int | str, model_id: str):
        p = self.resolve_provider(provider)
        m = self.db.get_model(p.id, model_id)
        return self.db.model_history(m.id)

    def results(self, run_id):
        return self.db.get_results(run_id)
