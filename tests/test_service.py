from llmbench.db import Database
from llmbench.domain import DiscoveredModel, SmokeResult, ModelStatus, RunStatus
from llmbench.service import BenchmarkService
from llmbench.benchmark.aiperf import BenchmarkOutcome

class FakeAdapter:
    def __init__(self): self.calls={}
    def discover_models(self,key): return [DiscoveredModel('good',{}),DiscoveredModel('flaky',{}),DiscoveredModel('bad',{})]
    def smoke_test(self,model_id,key,**kw):
        n=self.calls.get(model_id,0); self.calls[model_id]=n+1
        if model_id=='bad': return SmokeResult(False,400,'PAYLOAD_ERROR','bad payload',False)
        if model_id=='flaky' and n==1: return SmokeResult(False,503,'OVERLOADED','busy',True)
        return SmokeResult(True,200,content='ok')

class FakeRunner:
    def __init__(self): self.models=[]
    def run(self,**kw):
        self.models.append(kw['model_id'])
        return BenchmarkOutcome(10,0,{'ttft_p50':100.0,'latency_p50':500.0},[],aiperf_version='test')

def make_service(tmp_path,monkeypatch):
    monkeypatch.setenv('KEY','server-local-secret')
    db=Database(tmp_path/'db.sqlite3'); adapter=FakeAdapter(); runner=FakeRunner()
    svc=BenchmarkService(db,adapter_factory=lambda p:adapter,benchmark_runner=runner,artifact_root=tmp_path/'artifacts',stability_checks=2,retry_delays=())
    p=svc.add_provider('p','Provider','openai-compatible','https://example.test','KEY')
    svc.discover(p.id)
    return svc,db,adapter,runner,p

def test_pipeline_classifies_and_persists_history(tmp_path,monkeypatch):
    svc,db,adapter,runner,p=make_service(tmp_path,monkeypatch)
    run=svc.create_run(p.id,'full',requested_by='test')
    done=svc.execute_run(run.id)
    assert done.status==RunStatus.COMPLETED_WITH_ERRORS
    assert db.get_model(p.id,'good').status==ModelStatus.ACTIVE
    assert db.get_model(p.id,'flaky').status==ModelStatus.UNSTABLE
    assert db.get_model(p.id,'bad').status==ModelStatus.FAILED
    data=db.get_results(run.id)
    assert {r['model_id'] for r in data['results']}=={'good','flaky'}
    assert {e['model_id'] for e in data['errors']}=={'flaky','bad'}
    assert runner.models==['flaky','good'] or runner.models==['good','flaky']

def test_run_modes_select_expected_models(tmp_path,monkeypatch):
    svc,db,adapter,runner,p=make_service(tmp_path,monkeypatch)
    db.set_model_status(db.get_model(p.id,'good').id,ModelStatus.ACTIVE,'x')
    db.set_model_status(db.get_model(p.id,'flaky').id,ModelStatus.UNSTABLE,'x')
    assert [m.model_id for m in svc.select_models(p.id,'new')]==['bad']
    assert [m.model_id for m in svc.select_models(p.id,'active')]==['good']
    assert {m.model_id for m in svc.select_models(p.id,'unstable')}=={'flaky'}

def test_provider_validation_rejects_unsafe_url_and_bad_env(tmp_path):
    import pytest
    svc=BenchmarkService(Database(tmp_path/'v.db'))
    with pytest.raises(ValueError): svc.add_provider('x','X','openai-compatible','ftp://example.test','KEY')
    with pytest.raises(ValueError): svc.add_provider('x','X','openai-compatible','https://user:pass@example.test','KEY')
    with pytest.raises(ValueError): svc.add_provider('x','X','openai-compatible','https://example.test','1BAD')

def test_single_model_run_filters_other_models(tmp_path,monkeypatch):
    svc,db,adapter,runner,p=make_service(tmp_path,monkeypatch)
    run=svc.create_run(p.id,'full',requested_by='test',model_id='good')
    svc.execute_run(run.id)
    assert runner.models==['good']

def test_retryable_smoke_is_retried_with_backoff_and_marks_unstable(tmp_path,monkeypatch):
    monkeypatch.setenv('KEY','s')
    db=Database(tmp_path/'retry.db')
    class Recover:
        def __init__(self): self.n=0
        def discover_models(self,key): return [DiscoveredModel('m',{})]
        def smoke_test(self,*a,**k):
            self.n+=1
            if self.n<3: return SmokeResult(False,503,'OVERLOADED','busy',True)
            return SmokeResult(True,200,content='ok')
    adapter=Recover(); runner=FakeRunner(); sleeps=[]
    svc=BenchmarkService(db,adapter_factory=lambda p:adapter,benchmark_runner=runner,artifact_root=tmp_path/'a',stability_checks=0,retry_delays=(1,2,5,10),sleep_fn=sleeps.append)
    p=svc.add_provider('r','R','openai-compatible','https://x','KEY'); svc.discover(p.id)
    run=svc.create_run(p.id,'full'); svc.execute_run(run.id)
    assert adapter.n==3
    assert sleeps==[1,2]
    assert db.get_model(p.id,'m').status==ModelStatus.UNSTABLE
    assert len(db.get_results(run.id)['errors'])==2

def test_provider_error_message_is_secret_redacted(tmp_path,monkeypatch):
    monkeypatch.setenv('KEY','VERY-SECRET-VALUE')
    db=Database(tmp_path/'redact.db')
    class SecretEcho:
        def discover_models(self,key): return [DiscoveredModel('m',{})]
        def smoke_test(self,*a,**k): return SmokeResult(False,400,'PAYLOAD_ERROR','provider echoed VERY-SECRET-VALUE',False)
    svc=BenchmarkService(db,adapter_factory=lambda p:SecretEcho(),benchmark_runner=FakeRunner(),artifact_root=tmp_path/'a',retry_delays=())
    p=svc.add_provider('s','S','openai-compatible','https://x','KEY'); svc.discover(p.id)
    run=svc.create_run(p.id,'full'); svc.execute_run(run.id)
    msg=db.get_results(run.id)['errors'][0]['provider_message']
    assert 'VERY-SECRET-VALUE' not in msg and '<redacted>' in msg

def test_unexpected_execution_exception_marks_run_failed(tmp_path,monkeypatch):
    import pytest
    monkeypatch.setenv('KEY','s')
    db=Database(tmp_path/'boom.db')
    class Boom:
        def discover_models(self,key): return [DiscoveredModel('m',{})]
        def smoke_test(self,*a,**k): raise RuntimeError('boom')
    svc=BenchmarkService(db,adapter_factory=lambda p:Boom(),benchmark_runner=FakeRunner(),artifact_root=tmp_path/'a',retry_delays=())
    p=svc.add_provider('b','B','openai-compatible','https://x','KEY'); svc.discover(p.id); run=svc.create_run(p.id,'full')
    with pytest.raises(RuntimeError,match='boom'): svc.execute_run(run.id)
    assert db.get_run(run.id).status==RunStatus.FAILED

def test_add_provider_with_secret_derives_identity_and_never_stores_raw_secret(tmp_path):
    from llmbench.credentials import CredentialManager, SecureCredentialStore, EncryptedFileCredentialStore
    class FailingKeyring:
        class Backend: priority=0
        def get_keyring(self): return self.Backend()
    db=Database(tmp_path/'secure.db')
    manager=CredentialManager(secure_store=SecureCredentialStore(keyring_module=FailingKeyring(),fallback=EncryptedFileCredentialStore(tmp_path/'vault')))
    svc=BenchmarkService(db,credential_resolver=manager,artifact_root=tmp_path/'artifacts')
    p=svc.add_provider_with_secret('https://integrate.api.nvidia.com','dummy-provider-key')
    assert p.slug=='nvidia'
    assert p.name=='Nvidia'
    assert p.credential_source=='encrypted-file'
    assert p.credential_ref=='provider:nvidia'
    assert manager.resolve(p.credential_ref,p.credential_source)=='dummy-provider-key'
    assert 'dummy-provider-key' not in db.path.read_bytes().decode('latin1')

def test_add_provider_with_secret_makes_duplicate_slug_unique(tmp_path):
    from llmbench.credentials import CredentialManager, SecureCredentialStore, EncryptedFileCredentialStore
    class FailingKeyring:
        class Backend: priority=0
        def get_keyring(self): return self.Backend()
    db=Database(tmp_path/'dupe.db')
    manager=CredentialManager(secure_store=SecureCredentialStore(keyring_module=FailingKeyring(),fallback=EncryptedFileCredentialStore(tmp_path/'vault')))
    svc=BenchmarkService(db,credential_resolver=manager)
    a=svc.add_provider_with_secret('https://api.nvidia.com','one')
    b=svc.add_provider_with_secret('https://integrate.api.nvidia.com','two')
    assert a.slug=='nvidia' and b.slug=='nvidia-2'

def test_add_provider_with_secret_reuses_existing_provider_with_same_url(tmp_path):
    from llmbench.credentials import CredentialManager, SecureCredentialStore, EncryptedFileCredentialStore
    class FailingKeyring:
        class Backend: priority=0
        def get_keyring(self): return self.Backend()
    db=Database(tmp_path/'reuse.db')
    existing=db.add_provider('nvidia','NVIDIA','openai-compatible','https://integrate.api.nvidia.com','env','NVIDIA_API_KEY')
    manager=CredentialManager(secure_store=SecureCredentialStore(keyring_module=FailingKeyring(),fallback=EncryptedFileCredentialStore(tmp_path/'vault')))
    svc=BenchmarkService(db,credential_resolver=manager)
    updated=svc.add_provider_with_secret('https://integrate.api.nvidia.com/','dummy-provider-key')
    assert updated.id==existing.id
    assert updated.slug=='nvidia'
    assert updated.credential_source=='encrypted-file'
    assert updated.credential_ref=='provider:nvidia'
    assert manager.resolve(updated.credential_ref,updated.credential_source)=='dummy-provider-key'
    assert len(db.list_providers())==1


def test_404_model_is_not_available_without_retry_or_benchmark(tmp_path,monkeypatch):
    from llmbench.domain import ModelCapability
    monkeypatch.setenv('KEY','s')
    db=Database(tmp_path/'404.db'); sleeps=[]
    class Gone:
        def __init__(self): self.calls=0
        def discover_models(self,key): return [DiscoveredModel('gone-model',{})]
        def probe(self,model_id,key,capability):
            self.calls+=1; return SmokeResult(False,404,'MODEL_NOT_FOUND','not available for account',False)
        def smoke_test(self,*a,**k): return self.probe(a[0],a[1],ModelCapability.UNKNOWN)
        def benchmark_profile_for(self,capability): return 'baseline-v1' if capability is ModelCapability.CHAT_TEXT else None
    adapter=Gone(); runner=FakeRunner()
    svc=BenchmarkService(db,adapter_factory=lambda p:adapter,benchmark_runner=runner,artifact_root=tmp_path/'a',stability_checks=0,sleep_fn=sleeps.append)
    p=svc.add_provider('g','G','openai-compatible','https://x','KEY'); svc.discover(p.id)
    run=svc.create_run(p.id,'full'); svc.execute_run(run.id)
    assert db.get_model(p.id,'gone-model').status is ModelStatus.NOT_AVAILABLE
    assert adapter.calls == 1
    assert sleeps == []
    assert runner.models == []
    row=svc.run_progress(run.id)['models'][0]
    assert row['stage']=='DONE' and row['attempt_count']==1


def test_capability_mismatch_is_incompatible_and_probe_hint_is_persisted(tmp_path,monkeypatch):
    from llmbench.domain import ModelCapability
    monkeypatch.setenv('KEY','s')
    db=Database(tmp_path/'mismatch.db')
    class Mismatch:
        def __init__(self): self.calls=0
        def discover_models(self,key): return [DiscoveredModel('vendor/model-x',{})]
        def probe(self,model_id,key,capability):
            self.calls+=1
            return SmokeResult(False,400,'PAYLOAD_ERROR','Content cannot be a plain string. The model does not support text input.',False)
        def smoke_test(self,*a,**k): return self.probe(a[0],a[1],ModelCapability.UNKNOWN)
        def benchmark_profile_for(self,capability): return None
    adapter=Mismatch(); svc=BenchmarkService(db,adapter_factory=lambda p:adapter,benchmark_runner=FakeRunner(),artifact_root=tmp_path/'a',stability_checks=0)
    p=svc.add_provider('m','M','openai-compatible','https://x','KEY'); svc.discover(p.id)
    run=svc.create_run(p.id,'full'); svc.execute_run(run.id)
    m=db.get_model(p.id,'vendor/model-x')
    assert m.status is ModelStatus.INCOMPATIBLE
    assert m.capability is ModelCapability.UNKNOWN
    assert m.capability_source == 'probe'
    assert adapter.calls == 1


def test_error_specific_retry_schedules_and_recovery_marks_unstable(tmp_path,monkeypatch):
    from llmbench.domain import ModelCapability
    cases=[
        ('RATE_LIMITED',429,(1,2,5,10)),
        ('OVERLOADED',503,(1,2,5,10)),
        ('PROVIDER_ERROR',500,(1,3)),
        ('TIMEOUT',None,(1,3)),
    ]
    for error_type,status_code,expected in cases:
        monkeypatch.setenv('KEY','s')
        db=Database(tmp_path/f'{error_type}.db'); sleeps=[]
        class Recover:
            def __init__(self): self.calls=0
            def discover_models(self,key): return [DiscoveredModel('model',{'task':'text-generation'})]
            def probe(self,model_id,key,capability):
                self.calls+=1
                if self.calls <= len(expected): return SmokeResult(False,status_code,error_type,'temporary',True)
                return SmokeResult(True,200,content='ok')
            def smoke_test(self,*a,**k): return self.probe(a[0],a[1],ModelCapability.CHAT_TEXT)
            def benchmark_profile_for(self,capability): return 'baseline-v1'
        adapter=Recover(); runner=FakeRunner()
        svc=BenchmarkService(db,adapter_factory=lambda p:adapter,benchmark_runner=runner,artifact_root=tmp_path/error_type,stability_checks=0,sleep_fn=sleeps.append)
        p=svc.add_provider(error_type.lower(),error_type,'openai-compatible','https://x','KEY'); svc.discover(p.id)
        run=svc.create_run(p.id,'full'); svc.execute_run(run.id)
        assert tuple(sleeps)==expected
        assert db.get_model(p.id,'model').status is ModelStatus.UNSTABLE
        assert adapter.calls==len(expected)+1
