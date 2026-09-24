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
