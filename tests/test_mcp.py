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
