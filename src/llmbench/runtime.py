from __future__ import annotations
import os
from pathlib import Path
from .db import Database
from .service import BenchmarkService
from .jobs import LocalJobManager
from .benchmark.aiperf import AIPerfRunner

def build_runtime(data_dir:str|Path|None=None):
    root=Path(data_dir or os.environ.get('LLMBENCH_DATA_DIR') or Path.home()/'.local/share/llmbench')
    root.mkdir(parents=True,exist_ok=True)
    aiperf=os.environ.get('LLMBENCH_AIPERF','aiperf')
    svc=BenchmarkService(Database(root/'llmbench.db'),benchmark_runner=AIPerfRunner(aiperf),artifact_root=root/'artifacts')
    return svc,LocalJobManager()
