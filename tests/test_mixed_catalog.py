from llmbench.db import Database
from llmbench.domain import DiscoveredModel, SmokeResult, ModelStatus, ModelCapability
from llmbench.service import BenchmarkService
from llmbench.benchmark.aiperf import BenchmarkOutcome


class MixedAdapter:
    def __init__(self): self.calls={}
    def discover_models(self,key):
        return [
            DiscoveredModel('healthy-chat',{'task':'text-generation'}),
            DiscoveredModel('embed-model',{'task':'embeddings'}),
            DiscoveredModel('gone-model',{'task':'text-generation'}),
            DiscoveredModel('flaky-chat',{'task':'text-generation'}),
            DiscoveredModel('nemotron-parse',{}),
        ]
    def probe(self,model_id,key,capability):
        n=self.calls.get(model_id,0); self.calls[model_id]=n+1
        if model_id=='gone-model': return SmokeResult(False,404,'MODEL_NOT_FOUND','not found for account',False)
        if model_id=='flaky-chat' and n==0: return SmokeResult(False,503,'OVERLOADED','busy',True)
        if capability is ModelCapability.PARSER: return SmokeResult(False,None,'UNSUPPORTED','no generic probe',False)
        return SmokeResult(True,200,content='ok')
    def smoke_test(self,model_id,key,**kw): return self.probe(model_id,key,ModelCapability.CHAT_TEXT)
    def benchmark_profile_for(self,capability): return 'baseline-v1' if capability is ModelCapability.CHAT_TEXT else None


class Runner:
    def __init__(self): self.models=[]
    def run(self,**kw):
        self.models.append(kw['model_id'])
        return BenchmarkOutcome(10,0,{'ttft_p50':1.0},[],aiperf_version='fake')


def test_mixed_catalog_classifies_without_false_failures(tmp_path,monkeypatch):
    monkeypatch.setenv('KEY','s'); db=Database(tmp_path/'m.db'); adapter=MixedAdapter(); runner=Runner(); sleeps=[]
    svc=BenchmarkService(db,adapter_factory=lambda p:adapter,benchmark_runner=runner,artifact_root=tmp_path/'a',stability_checks=0,sleep_fn=sleeps.append)
    p=svc.add_provider('p','P','openai-compatible','https://x','KEY'); svc.discover(p.id)
    run=svc.create_run(p.id,'full'); svc.execute_run(run.id)
    statuses={m.model_id:m.status for m in db.list_models(p.id)}
    assert statuses['healthy-chat'] is ModelStatus.ACTIVE
    assert statuses['embed-model'] is ModelStatus.ACTIVE
    assert statuses['gone-model'] is ModelStatus.NOT_AVAILABLE
    assert statuses['flaky-chat'] is ModelStatus.UNSTABLE
    assert statuses['nemotron-parse'] is ModelStatus.UNSUPPORTED
    assert ModelStatus.FAILED not in statuses.values()
    assert set(runner.models)=={'healthy-chat','flaky-chat'}
    progress=svc.run_progress(run.id)
    assert (progress['total'],progress['processed'],progress['percent'])==(5,5,100.0)
