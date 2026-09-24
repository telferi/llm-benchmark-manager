from __future__ import annotations
from pathlib import Path
from dataclasses import asdict
from typing import Callable
from urllib.parse import urlparse
import re, time
from .db import Database
from .domain import ModelStatus, RunStatus, Provider
from .credentials import CredentialManager, redact_text
from .discovery import DiscoveryService
from .providers.openai_compatible import OpenAICompatibleProvider
from .benchmark.aiperf import AIPerfRunner, AIPerfUnavailable, AIPerfError
from .benchmark.profiles import BASELINE_V1

RETRYABLE_HTTP={429,500,502,503,504}

def _safe_component(value:str)->str:
    out=''.join(c if c.isalnum() or c in '-_.' else '_' for c in value)
    while '..' in out: out=out.replace('..','_')
    return out[:180] or 'model'

class BenchmarkService:
    def __init__(self,db:Database,credential_resolver=None,adapter_factory=None,benchmark_runner=None,artifact_root=None,stability_checks:int=3,retry_delays=(1,2,5,10),sleep_fn=None):
        self.db=db; self.credentials=credential_resolver or CredentialManager()
        self.adapter_factory=adapter_factory or self._default_adapter
        self.benchmark_runner=benchmark_runner or AIPerfRunner()
        self.artifact_root=Path(artifact_root or Path.home()/'.local/share/llmbench/artifacts')
        self.stability_checks=max(0,int(stability_checks)); self.retry_delays=tuple(retry_delays); self.sleep_fn=sleep_fn or time.sleep; self.discovery_service=DiscoveryService(db)
    def _default_adapter(self,p:Provider):
        if p.provider_type not in ('openai-compatible','openai_compatible','openai'): raise ValueError(f'unsupported provider type: {p.provider_type}')
        return OpenAICompatibleProvider(p.base_url)
    def resolve_provider(self,value:int|str):
        if isinstance(value,int) or (isinstance(value,str) and value.isdigit()): return self.db.get_provider(int(value))
        return self.db.get_provider_by_slug(str(value))
    def _validated_url(self,base_url:str):
        u=urlparse(base_url)
        if u.scheme not in ('http','https') or not u.netloc or u.username or u.password:
            raise ValueError('provider URL must be http(s) and must not embed credentials')
        return u
    def _identity_from_url(self,base_url:str):
        u=self._validated_url(base_url); host=(u.hostname or '').lower()
        labels=[x for x in host.split('.') if x]
        generic={'www','api','integrate','gateway','cloud','v1','com','net','org','io','ai','co','uk','dev'}
        candidates=[x for x in labels if x not in generic and not x.isdigit()]
        base=(candidates[-1] if candidates else (labels[0] if labels else 'provider'))
        slug=re.sub(r'[^a-z0-9]+','-',base.lower()).strip('-') or 'provider'
        existing={p.slug for p in self.db.list_providers()}; unique=slug; n=2
        while unique in existing:
            unique=f'{slug}-{n}'; n+=1
        return unique, base.replace('-',' ').title()
    def add_provider(self,slug,name,provider_type,base_url,credential_env):
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', credential_env or ''): raise ValueError('invalid credential ENV variable name')
        self._validated_url(base_url)
        return self.db.add_provider(slug,name,provider_type,base_url,'env',credential_env)
    def add_provider_with_secret(self,base_url,api_key,provider_type='openai-compatible'):
        if not api_key: raise ValueError('API key cannot be empty')
        self._validated_url(base_url); normalized=base_url.rstrip('/')
        existing=next((p for p in self.db.list_providers() if p.base_url.rstrip('/')==normalized),None)
        if existing is not None:
            ref=f'provider:{existing.slug}'
            source,stored_ref=self.credentials.store(ref,api_key)
            try:
                return self.db.update_provider_credential(existing.id,source,stored_ref)
            except Exception:
                self.credentials.delete(source,stored_ref)
                raise
        slug,name=self._identity_from_url(normalized); ref=f'provider:{slug}'
        source,stored_ref=self.credentials.store(ref,api_key)
        try:
            return self.db.add_provider(slug,name,provider_type,normalized,source,stored_ref)
        except Exception:
            self.credentials.delete(source,stored_ref)
            raise
    def list_providers(self): return self.db.list_providers()
    def provider_view(self,p:Provider):
        d=asdict(p); d['credential_available']=self.credentials.availability(p.credential_ref,p.credential_source); return d
    def discover(self,provider:int|str):
        p=self.resolve_provider(provider); key=self.credentials.resolve(p.credential_ref,p.credential_source); adapter=self.adapter_factory(p)
        discovered=adapter.discover_models(key); result=self.discovery_service.reconcile(p.id,[x.model_id for x in discovered])
        for d in discovered:
            current=self.db.get_model(p.id,d.model_id); self.db.upsert_model(p.id,d.model_id,current.status,d.metadata)
        return result
    def select_models(self,provider:int|str,mode:str):
        p=self.resolve_provider(provider); models=self.db.list_models(p.id); mode=mode.lower()
        if mode=='full': return [m for m in models if m.status not in (ModelStatus.DISABLED,ModelStatus.MISSING)]
        if mode=='new': statuses={ModelStatus.NEW}
        elif mode=='active': statuses={ModelStatus.ACTIVE}
        elif mode in ('unstable','unstable_failed'): statuses={ModelStatus.UNSTABLE} if mode=='unstable' else {ModelStatus.UNSTABLE,ModelStatus.FAILED}
        elif mode=='failed': statuses={ModelStatus.FAILED}
        else: raise ValueError(f'unknown run mode: {mode}')
        return [m for m in models if m.status in statuses]
    def create_run(self,provider:int|str,mode='full',requested_by='cli',profile='baseline-v1',model_id:str|None=None):
        p=self.resolve_provider(provider); config={'model_id':model_id} if model_id else {}
        return self.db.create_run(p.id,mode,profile,requested_by,config=config)
    def _record_smoke_error(self,run_id,m,result,secret=None):
        self.db.add_error(run_id,m.id,result.error_type or 'SMOKE_ERROR',redact_text(result.message or '',(secret,)),result.status_code,1)
    def _smoke_with_retry(self,adapter,model_id,key):
        prior=[]; result=adapter.smoke_test(model_id,key)
        for delay in self.retry_delays:
            if result.ok or not result.retryable: break
            prior.append(result); self.sleep_fn(delay); result=adapter.smoke_test(model_id,key)
        return result,prior
    def execute_run(self,run_id:str,cancel_check:Callable[[],bool]|None=None):
        cancelled=cancel_check or (lambda:False); run=self.db.get_run(run_id); p=self.db.get_provider(run.provider_id)
        self.db.update_run_status(run_id,RunStatus.RUNNING)
        try: key=self.credentials.resolve(p.credential_ref,p.credential_source); adapter=self.adapter_factory(p)
        except Exception:
            self.db.update_run_status(run_id,RunStatus.FAILED); raise
        had_errors=False; aiperf_version=None
        models=self.select_models(p.id,run.mode)
        if run.config.get('model_id'): models=[m for m in models if m.model_id==run.config['model_id']]
        for m in models:
            if cancelled(): return self.db.update_run_status(run_id,RunStatus.CANCELLED)
            try:
                smoke,retry_failures=self._smoke_with_retry(adapter,m.model_id,key)
            except Exception:
                self.db.update_run_status(run_id,RunStatus.FAILED); raise
            unstable=bool(retry_failures)
            for failure in retry_failures:
                had_errors=True; self._record_smoke_error(run_id,m,failure,key)
            if not smoke.ok:
                had_errors=True; self._record_smoke_error(run_id,m,smoke,key)
                status=ModelStatus.UNSTABLE if smoke.retryable else (ModelStatus.UNSUPPORTED if smoke.error_type=='UNSUPPORTED' else ModelStatus.FAILED)
                self.db.set_model_status(m.id,status,smoke.error_type or 'smoke failure'); continue
            permanent_failure=False
            for _ in range(self.stability_checks):
                if cancelled(): return self.db.update_run_status(run_id,RunStatus.CANCELLED)
                try:
                    check,retry_failures=self._smoke_with_retry(adapter,m.model_id,key)
                except Exception:
                    self.db.update_run_status(run_id,RunStatus.FAILED); raise
                if retry_failures:
                    unstable=True
                    for failure in retry_failures:
                        had_errors=True; self._record_smoke_error(run_id,m,failure,key)
                if check.ok: continue
                had_errors=True; self._record_smoke_error(run_id,m,check,key)
                if check.retryable: unstable=True; continue
                permanent_failure=True; self.db.set_model_status(m.id,ModelStatus.FAILED,check.error_type or 'stability failure'); break
            if permanent_failure: continue
            art=self.artifact_root/_safe_component(p.slug)/run_id/_safe_component(m.model_id)
            try:
                out=self.benchmark_runner.run(model_id=m.model_id,base_url=p.base_url,api_key=key,profile=BASELINE_V1,artifact_dir=art)
            except (AIPerfUnavailable,AIPerfError) as e:
                had_errors=True; self.db.add_error(run_id,m.id,type(e).__name__,redact_text(str(e),(key,))); continue
            except Exception:
                self.db.update_run_status(run_id,RunStatus.FAILED); raise
            aiperf_version=out.aiperf_version or aiperf_version
            self.db.add_result(run_id,m.id,success_count=out.success_count,error_count=out.error_count,metrics=out.metrics,raw_artifact_path=out.artifact_path)
            if out.error_count: unstable=True; had_errors=True
            for err in out.errors:
                self.db.add_error(run_id,m.id,err.get('error_type','INFERENCE_ERROR'),redact_text(err.get('message',''),(key,)),err.get('http_status'),err.get('count',1));
                if err.get('http_status') in RETRYABLE_HTTP: unstable=True
            self.db.set_model_status(m.id,ModelStatus.UNSTABLE if unstable else ModelStatus.ACTIVE,'benchmark complete')
        status=RunStatus.COMPLETED_WITH_ERRORS if had_errors else RunStatus.COMPLETED
        return self.db.update_run_status(run_id,status,aiperf_version)
    def model_history(self,provider:int|str,model_id:str):
        p=self.resolve_provider(provider); m=self.db.get_model(p.id,model_id); return self.db.model_history(m.id)
    def results(self,run_id): return self.db.get_results(run_id)
