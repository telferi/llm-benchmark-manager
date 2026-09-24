from fastapi.testclient import TestClient
from llmbench.api import create_app
from llmbench.db import Database
from llmbench.domain import DiscoveredModel, SmokeResult
from llmbench.service import BenchmarkService
from llmbench.jobs import LocalJobManager
from llmbench.benchmark.aiperf import BenchmarkOutcome

class A:
    def discover_models(self,key): return [DiscoveredModel('m1',{})]
    def smoke_test(self,*a,**k): return SmokeResult(True,200,content='ok')
class R:
    def run(self,**k): return BenchmarkOutcome(10,0,{'ttft_p50':12.0},[],aiperf_version='test')

def test_rest_provider_discovery_run_and_no_secret(tmp_path,monkeypatch):
    monkeypatch.setenv('KEY','TOP-SECRET-VALUE')
    svc=BenchmarkService(Database(tmp_path/'d.db'),adapter_factory=lambda p:A(),benchmark_runner=R(),artifact_root=tmp_path/'a',stability_checks=1)
    jobs=LocalJobManager(); client=TestClient(create_app(svc,jobs))
    r=client.post('/api/v1/providers',json={'slug':'p','name':'P','provider_type':'openai-compatible','base_url':'https://x','credential_env':'KEY'}); assert r.status_code==201
    body=r.text; assert 'TOP-SECRET-VALUE' not in body and 'KEY' in body
    pid=r.json()['id']
    assert client.post(f'/api/v1/providers/{pid}/discover').status_code==200
    rr=client.post('/api/v1/runs',json={'provider':'p','mode':'full'}); assert rr.status_code==202
    run_id=rr.json()['run_id']; jobs.wait(run_id,2)
    status=client.get(f'/api/v1/runs/{run_id}').json(); assert status['status']=='COMPLETED'
    results=client.get(f'/api/v1/runs/{run_id}/results').json(); assert results['results'][0]['model_id']=='m1'
    assert 'TOP-SECRET-VALUE' not in str(results)
