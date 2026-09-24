from llmbench.db import Database
from llmbench.service import BenchmarkService
from llmbench.cli import main
from llmbench.jobs import LocalJobManager


def service(tmp_path):
    return BenchmarkService(Database(tmp_path/'d.db'))


def test_no_args_opens_menu_and_can_exit(tmp_path,monkeypatch,capsys):
    monkeypatch.setattr('builtins.input',lambda p='':'6')
    assert main([],service=service(tmp_path),jobs=LocalJobManager())==0
    assert 'New provider' in capsys.readouterr().out


def test_cli_add_and_list_env_provider_without_secret_value(tmp_path,capsys):
    svc=service(tmp_path); jobs=LocalJobManager()
    rc=main(['provider','add','--slug','nvidia','--name','NVIDIA','--url','https://integrate.api.nvidia.com','--credential-env','NVIDIA_API_KEY'],service=svc,jobs=jobs)
    assert rc==0
    main(['provider','list'],service=svc,jobs=jobs)
    out=capsys.readouterr().out
    assert 'nvidia' in out and 'NVIDIA_API_KEY' in out
    assert 'nvapi-' not in out


def test_interactive_new_provider_asks_only_url_and_hidden_key_then_benchmarks(tmp_path,monkeypatch,capsys):
    from llmbench.domain import DiscoveredModel, SmokeResult, ModelStatus
    from llmbench.benchmark.aiperf import BenchmarkOutcome
    from llmbench.credentials import CredentialManager, SecureCredentialStore, EncryptedFileCredentialStore

    class FailingKeyring:
        class Backend: priority=0
        def get_keyring(self): return self.Backend()
    class Adapter:
        def discover_models(self,key):
            assert key=='nvapi-hidden'
            return [DiscoveredModel('m',{})]
        def smoke_test(self,*a,**k): return SmokeResult(True,200,content='ok')
    class Runner:
        def run(self,**k): return BenchmarkOutcome(10,0,{},[],aiperf_version='test')

    manager=CredentialManager(secure_store=SecureCredentialStore(keyring_module=FailingKeyring(),fallback=EncryptedFileCredentialStore(tmp_path/'vault')))
    svc=BenchmarkService(Database(tmp_path/'onboard.db'),credential_resolver=manager,adapter_factory=lambda p:Adapter(),benchmark_runner=Runner(),artifact_root=tmp_path/'a',stability_checks=0,retry_delays=())
    answers=iter(['1','https://integrate.api.nvidia.com','6'])
    prompts=[]
    monkeypatch.setattr('builtins.input',lambda prompt='': (prompts.append(prompt),next(answers))[1])
    import getpass
    secret_prompts=[]
    monkeypatch.setattr(getpass,'getpass',lambda prompt='': (secret_prompts.append(prompt),'nvapi-hidden')[1])

    assert main([],service=svc,jobs=LocalJobManager())==0
    pr=svc.resolve_provider('nvidia')
    assert pr.name=='Nvidia'
    assert pr.credential_source=='encrypted-file'
    assert svc.db.get_model(pr.id,'m').status==ModelStatus.ACTIVE
    assert not any('slug' in prompt.lower() or 'name' in prompt.lower() or 'env' in prompt.lower() for prompt in prompts)
    assert secret_prompts==['API key: ']
    assert 'nvapi-hidden' not in capsys.readouterr().out
