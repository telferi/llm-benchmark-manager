from llmbench.db import Database
from llmbench.domain import DiscoveredModel, SmokeResult, ModelStatus, ModelCapability
from llmbench.service import BenchmarkService
from llmbench.benchmark.aiperf import BenchmarkOutcome


class Runner:
    def __init__(self): self.models=[]
    def run(self,**kw):
        self.models.append(kw['model_id'])
        return BenchmarkOutcome(10,0,{'ttft_p50':1.0},[],aiperf_version='fake')


class CapabilityAdapter:
    def __init__(self,models): self.models=models
    def discover_models(self,key): return [DiscoveredModel(mid,meta) for mid,meta in self.models]
    def probe(self,model_id,key,capability): return SmokeResult(True,200,content='ok')
    def smoke_test(self,*a,**k): return SmokeResult(True,200,content='ok')
    def benchmark_profile_for(self,capability): return 'baseline-v1' if capability is ModelCapability.CHAT_TEXT else None


def test_embedding_skips_text_aiperf_but_finishes_active(tmp_path,monkeypatch):
    monkeypatch.setenv('KEY','s'); db=Database(tmp_path/'e.db'); runner=Runner()
    adapter=CapabilityAdapter([('embed-model',{'task':'embeddings'})])
    svc=BenchmarkService(db,adapter_factory=lambda p:adapter,benchmark_runner=runner,artifact_root=tmp_path/'a',stability_checks=0)
    p=svc.add_provider('p','P','openai-compatible','https://x','KEY'); svc.discover(p.id)
    run=svc.create_run(p.id,'full'); svc.execute_run(run.id)
    assert db.get_model(p.id,'embed-model').status is ModelStatus.ACTIVE
    assert runner.models == []
    row=svc.run_progress(run.id)['models'][0]
    assert row['outcome']=='SKIPPED_UNSUPPORTED_PROFILE'
    assert row['stage']=='DONE'


def test_chat_text_calls_aiperf(tmp_path,monkeypatch):
    monkeypatch.setenv('KEY','s'); db=Database(tmp_path/'c.db'); runner=Runner()
    adapter=CapabilityAdapter([('chat-model',{'task':'text-generation'})])
    svc=BenchmarkService(db,adapter_factory=lambda p:adapter,benchmark_runner=runner,artifact_root=tmp_path/'a',stability_checks=0)
    p=svc.add_provider('p','P','openai-compatible','https://x','KEY'); svc.discover(p.id)
    run=svc.create_run(p.id,'full'); svc.execute_run(run.id)
    assert runner.models == ['chat-model']


def test_progress_denominator_is_selected_models_and_callbacks_show_stage_order(tmp_path,monkeypatch):
    monkeypatch.setenv('KEY','s'); db=Database(tmp_path/'p.db'); runner=Runner()
    models=[
        ('chat-model',{'task':'text-generation'}),
        ('embed-model',{'task':'embeddings'}),
        ('parse-model',{}),
        ('safety-model',{}),
        ('translate-model',{}),
    ]
    adapter=CapabilityAdapter(models)
    events=[]
    svc=BenchmarkService(db,adapter_factory=lambda p:adapter,benchmark_runner=runner,artifact_root=tmp_path/'a',stability_checks=0)
    p=svc.add_provider('p','P','openai-compatible','https://x','KEY'); svc.discover(p.id)
    run=svc.create_run(p.id,'full'); svc.execute_run(run.id,progress_callback=events.append)
    progress=svc.run_progress(run.id)
    assert progress['total']==5
    assert progress['processed']==5
    assert progress['percent']==100.0
    assert len(db.get_results(run.id)['results'])==1
    per_model={}
    for event in events:
        e=event.get('event') or {}
        if e.get('model_id'):
            per_model.setdefault(e['model_id'],[]).append(e['stage'])
    for model_id in [m[0] for m in models]:
        assert per_model[model_id][0]=='CAPABILITY'
        assert 'SMOKE' in per_model[model_id]
        assert per_model[model_id][-1]=='DONE'
    assert 'BENCHMARK' in per_model['chat-model']


def test_live_by_status_counts_only_done_rows(tmp_path,monkeypatch):
    monkeypatch.setenv('KEY','s')
    db=Database(tmp_path/'live-status.db')
    svc=BenchmarkService(db)
    p=svc.add_provider('p','P','openai-compatible','https://x','KEY')
    m1=db.upsert_model(p.id,'m1',ModelStatus.ACTIVE,{})
    m2=db.upsert_model(p.id,'m2',ModelStatus.ACTIVE,{})
    run=db.create_run(p.id,'full')
    db.init_run_progress(run.id,[m1,m2])
    db.update_run_progress(run.id,m1.id,stage='DONE',outcome='ACTIVE',finished=True)
    progress=svc.run_progress(run.id)
    assert progress['processed']==1
    assert progress['by_status']=={'ACTIVE':1}


def test_callback_emits_smoke_pass_outcome(tmp_path,monkeypatch):
    monkeypatch.setenv('KEY','s'); db=Database(tmp_path/'callback-outcome.db'); runner=Runner()
    adapter=CapabilityAdapter([('chat-model',{'task':'text-generation'})])
    events=[]
    svc=BenchmarkService(db,adapter_factory=lambda p:adapter,benchmark_runner=runner,artifact_root=tmp_path/'a',stability_checks=0)
    p=svc.add_provider('p','P','openai-compatible','https://x','KEY'); svc.discover(p.id)
    run=svc.create_run(p.id,'full'); svc.execute_run(run.id,progress_callback=events.append)
    assert any((e.get('event') or {}).get('stage')=='SMOKE' and (e.get('event') or {}).get('outcome')=='PASS' for e in events)


def test_historical_run_by_status_uses_persisted_run_outcome_not_current_model_status(tmp_path,monkeypatch):
    monkeypatch.setenv('KEY','s')
    db=Database(tmp_path/'historical-status.db')
    svc=BenchmarkService(db)
    p=svc.add_provider('p','P','openai-compatible','https://x','KEY')
    m=db.upsert_model(p.id,'m1',ModelStatus.ACTIVE,{})
    run=db.create_run(p.id,'full')
    db.init_run_progress(run.id,[m])
    db.update_run_progress(run.id,m.id,stage='DONE',outcome='ACTIVE',finished=True)

    # A later retest changes the model's current status. Historical run summary
    # must remain an immutable view of what that run concluded.
    db.set_model_status(m.id,ModelStatus.UNSTABLE,'later retest')

    progress=svc.run_progress(run.id)
    assert progress['by_status']=={'ACTIVE':1}


def test_historical_skipped_benchmark_keeps_run_final_status_after_later_retest(tmp_path,monkeypatch):
    monkeypatch.setenv('KEY','s')
    db=Database(tmp_path/'historical-skip.db'); runner=Runner()
    adapter=CapabilityAdapter([('embed-model',{'task':'embeddings'})])
    svc=BenchmarkService(db,adapter_factory=lambda p:adapter,benchmark_runner=runner,artifact_root=tmp_path/'a',stability_checks=0)
    p=svc.add_provider('p','P','openai-compatible','https://x','KEY'); svc.discover(p.id)
    run=svc.create_run(p.id,'full'); svc.execute_run(run.id)
    model=db.get_model(p.id,'embed-model')
    assert svc.run_progress(run.id)['by_status']=={'ACTIVE':1}
    assert svc.run_progress(run.id)['models'][0]['outcome']=='SKIPPED_UNSUPPORTED_PROFILE'

    db.set_model_status(model.id,ModelStatus.UNSTABLE,'later retest')

    progress=svc.run_progress(run.id)
    assert progress['by_status']=={'ACTIVE':1}
    assert progress['models'][0]['outcome']=='SKIPPED_UNSUPPORTED_PROFILE'
