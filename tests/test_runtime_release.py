import types
import tomllib
from pathlib import Path

from llmbench import runtime
from llmbench import paths
from llmbench.service import BenchmarkService
from llmbench.db import Database


def test_build_runtime_uses_platformdirs_xdg_data_home(monkeypatch, tmp_path):
    home = tmp_path / "home"
    xdg = tmp_path / "xdg"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg))
    monkeypatch.delenv("LLMBENCH_DATA_DIR", raising=False)
    svc, _ = runtime.build_runtime()
    assert svc.db.path == xdg / "llmbench" / "llmbench.db"
    assert svc.artifact_root == xdg / "llmbench" / "artifacts"


def test_build_runtime_prefers_aiperf_from_same_python_environment(monkeypatch, tmp_path):
    bindir = tmp_path / "venv" / "bin"
    bindir.mkdir(parents=True)
    python = bindir / "python"
    aiperf = bindir / "aiperf"
    python.write_text("")
    aiperf.write_text("#!/bin/sh\n")
    aiperf.chmod(0o755)
    monkeypatch.setattr(paths, "sys", types.SimpleNamespace(executable=str(python)))
    monkeypatch.setenv("PATH", "")
    monkeypatch.delenv("LLMBENCH_AIPERF", raising=False)
    svc, _ = runtime.build_runtime(data_dir=tmp_path / "data")
    assert svc.benchmark_runner.executable == str(aiperf)


def test_release_declares_aiperf_as_required_dependency():
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert "aiperf==0.12.0" in data["project"]["dependencies"]


def test_release_version_is_030_and_metadata_matches_package():
    import llmbench
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert llmbench.__version__ == "0.3.0"
    assert data["project"]["version"] == llmbench.__version__


def test_direct_service_default_artifacts_follow_platform_data_home(monkeypatch, tmp_path):
    home = tmp_path / "home"
    xdg = tmp_path / "xdg"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg))
    svc = BenchmarkService(Database(tmp_path / "db.sqlite3"))
    assert svc.artifact_root == xdg / "llmbench" / "artifacts"


def test_aiperf_resolution_keeps_virtualenv_bin_when_python_is_symlink(monkeypatch, tmp_path):
    realbin = tmp_path / "usr" / "bin"
    venvbin = tmp_path / "venv" / "bin"
    realbin.mkdir(parents=True)
    venvbin.mkdir(parents=True)
    real_python = realbin / "python3"
    real_python.write_text("")
    venv_python = venvbin / "python"
    venv_python.symlink_to(real_python)
    aiperf = venvbin / "aiperf"
    aiperf.write_text("#!/bin/sh\n")
    aiperf.chmod(0o755)
    monkeypatch.setattr(paths, "sys", types.SimpleNamespace(executable=str(venv_python)))
    monkeypatch.setenv("PATH", "")
    monkeypatch.delenv("LLMBENCH_AIPERF", raising=False)
    assert paths.resolve_aiperf_executable() == str(aiperf)
