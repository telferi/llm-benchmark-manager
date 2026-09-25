from __future__ import annotations
from pathlib import Path
from .db import Database
from .service import BenchmarkService
from .jobs import LocalJobManager
from .benchmark.aiperf import AIPerfRunner
from .credentials import CredentialManager
from .paths import resolve_aiperf_executable, resolve_data_dir


def build_runtime(data_dir: str | Path | None = None):
    root = resolve_data_dir(data_dir)
    root.mkdir(parents=True, exist_ok=True)
    credentials = CredentialManager(data_dir=root / "credentials")
    svc = BenchmarkService(
        Database(root / "llmbench.db"),
        credential_resolver=credentials,
        benchmark_runner=AIPerfRunner(resolve_aiperf_executable()),
        artifact_root=root / "artifacts",
    )
    return svc, LocalJobManager()
