from llmbench import __version__
from llmbench.api import create_app
from llmbench.db import Database
from llmbench.service import BenchmarkService
from llmbench.jobs import LocalJobManager


def test_runtime_and_api_report_release_version(tmp_path):
    assert __version__ == '0.3.0'
    app=create_app(BenchmarkService(Database(tmp_path/'d.db')),LocalJobManager())
    assert app.version == '0.3.0'
