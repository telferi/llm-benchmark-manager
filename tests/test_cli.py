from llmbench.db import Database
from llmbench.service import BenchmarkService
from llmbench.cli import main
from llmbench.jobs import LocalJobManager

def service(tmp_path): return BenchmarkService(Database(tmp_path/'d.db'))

def test_no_args_opens_menu_and_can_exit(tmp_path,monkeypatch,capsys):
    monkeypatch.setattr('builtins.input',lambda p='':'6')
    assert main([],service=service(tmp_path),jobs=LocalJobManager())==0
    assert 'New provider' in capsys.readouterr().out

def test_cli_add_and_list_provider_without_secret_value(tmp_path,capsys):
    svc=service(tmp_path); jobs=LocalJobManager()
    rc=main(['provider','add','--slug','nvidia','--name','NVIDIA','--url','https://integrate.api.nvidia.com','--credential-env','NVIDIA_API_KEY'],service=svc,jobs=jobs)
    assert rc==0
    main(['provider','list'],service=svc,jobs=jobs)
    out=capsys.readouterr().out
    assert 'nvidia' in out and 'NVIDIA_API_KEY' in out
    assert 'nvapi-' not in out

def test_interactive_new_provider_onboards_and_benchmarks(tmp_path,monkeypatch):
    from llmbench.domain import DiscoveredModel, SmokeResult, ModelStatus
    from llmbench.benchmark.aiperf import BenchmarkOutcome
    class A:
        def discover_models(self,key): return [DiscoveredModel('m',{})]
        def smoke_test(self,*a,**k): return SmokeResult(True,200,content='ok')
    class R:
        def run(self,**k): return BenchmarkOutcome(10,0,{},[],aiperf_version='test')
    monkeypatch.setenv('KEY','s')
    svc=BenchmarkService(Database(tmp_path/'onboard.db'),adapter_factory=lambda p:A(),benchmark_runner=R(),artifact_root=tmp_path/'a',stability_checks=0,retry_delays=())
    answers=iter(['1','p','P','https://x','KEY','6'])
    monkeypatch.setattr('builtins.input',lambda p='':next(answers))
    assert main([],service=svc,jobs=LocalJobManager())==0
    pr=svc.resolve_provider('p')
    assert svc.db.get_model(pr.id,'m').status==ModelStatus.ACTIVE
