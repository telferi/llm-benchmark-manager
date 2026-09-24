from llmbench.db import Database
from llmbench.domain import DiscoveredModel, SmokeResult, ModelStatus
from llmbench.service import BenchmarkService
from llmbench.benchmark.aiperf import BenchmarkOutcome
class Adapter:
    def discover_models(self,key): return [DiscoveredModel('one',{})]
    def smoke_test(self,*a,**k): return SmokeResult(True,200,content='hello')
class Runner:
    def run(self,**k): return BenchmarkOutcome(10,0,{'ttft_p50':1.0},[],aiperf_version='fake')
def test_end_to_end_fake_provider(tmp_path,monkeypatch):
    monkeypatch.setenv('KEY','s')
    db=Database(tmp_path/'d.db'); svc=BenchmarkService(db,adapter_factory=lambda p:Adapter(),benchmark_runner=Runner(),artifact_root=tmp_path/'art',stability_checks=1)
    p=svc.add_provider('demo','Demo','openai-compatible','https://demo','KEY'); svc.discover(p.id)
    run=svc.create_run(p.id,'full'); svc.execute_run(run.id)
    assert db.get_model(p.id,'one').status==ModelStatus.ACTIVE
    assert db.get_results(run.id)['results'][0]['success_count']==10
