from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from platformdirs import user_data_path


def default_data_dir() -> Path:
    return Path(user_data_path("llmbench", appauthor=False))


def resolve_data_dir(data_dir: str | Path | None = None) -> Path:
    if data_dir is not None:
        return Path(data_dir)
    configured = os.environ.get("LLMBENCH_DATA_DIR")
    if configured:
        return Path(configured)
    return default_data_dir()


def resolve_aiperf_executable() -> str:
    configured = os.environ.get("LLMBENCH_AIPERF")
    if configured:
        return configured

    name = "aiperf.exe" if os.name == "nt" else "aiperf"
    sibling = Path(sys.executable).with_name(name)
    if sibling.is_file():
        return str(sibling)

    found = shutil.which("aiperf")
    return found or "aiperf"
