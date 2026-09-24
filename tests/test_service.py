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
