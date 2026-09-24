from fastmcp import FastMCP
from llmbench.mcp_server import build_mcp_server, get_mcp_tool_functions, MCP_TOOL_NAMES
from llmbench.db import Database
from llmbench.service import BenchmarkService
from llmbench.jobs import LocalJobManager

def test_mcp_surface_has_safe_tools_only(tmp_path):
    svc=BenchmarkService(Database(tmp_path/'d.db')); jobs=LocalJobManager()
    server=build_mcp_server(svc,jobs)
    assert isinstance(server,FastMCP)
    assert 'benchmark_run_start' in MCP_TOOL_NAMES
    assert not any('raw' in n or 'secret_read' in n for n in MCP_TOOL_NAMES)
    funcs=get_mcp_tool_functions(svc,jobs)
    assert set(funcs)==set(MCP_TOOL_NAMES)
    assert funcs['benchmark_provider_list']()==[]


def test_mcp_exposes_safe_benchmark_run_progress(tmp_path,monkeypatch):
    from llmbench.domain import ModelStatus
    monkeypatch.setenv('KEY','fixture-credential-value')
    db=Database(tmp_path/'p.db'); svc=BenchmarkService(db); jobs=LocalJobManager()
    p=svc.add_provider('p','P','openai-compatible','https://x','KEY')
    m=db.upsert_model(p.id,'m',ModelStatus.ACTIVE,{})
    run=db.create_run(p.id,'full')
    db.init_run_progress(run.id,[m])
    db.update_run_progress(run.id,m.id,stage='DONE',outcome='ACTIVE',finished=True)
    assert 'benchmark_run_progress' in MCP_TOOL_NAMES
    funcs=get_mcp_tool_functions(svc,jobs)
    result=funcs['benchmark_run_progress'](run.id)
    assert result['total']==1 and result['processed']==1 and result['percent']==100.0
    assert 'fixture-credential-value' not in str(result)
