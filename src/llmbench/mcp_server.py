from __future__ import annotations
from dataclasses import asdict
from enum import Enum
from typing import Any, Callable
from fastmcp import FastMCP

MCP_TOOL_NAMES=(
 'benchmark_provider_list','benchmark_provider_get','benchmark_provider_discover',
 'benchmark_model_list','benchmark_model_get','benchmark_model_history',
 'benchmark_run_start','benchmark_run_status','benchmark_run_cancel','benchmark_run_results',
 'benchmark_retest_unstable','benchmark_test_new_models')

def _j(v:Any):
    if isinstance(v,Enum): return v.value
    if hasattr(v,'__dataclass_fields__'): return _j(asdict(v))
    if isinstance(v,dict): return {k:_j(x) for k,x in v.items()}
    if isinstance(v,(list,tuple,set)): return [_j(x) for x in v]
    return v

def get_mcp_tool_functions(service,jobs)->dict[str,Callable]:
    def benchmark_provider_list()->list[dict]: return [_j(service.provider_view(p)) for p in service.list_providers()]
    def benchmark_provider_get(provider:str)->dict: return _j(service.provider_view(service.resolve_provider(provider)))
    def benchmark_provider_discover(provider:str)->dict: return _j(service.discover(provider))
    def benchmark_model_list(provider:str)->list[dict]:
        p=service.resolve_provider(provider); return [_j(m) for m in service.db.list_models(p.id)]
    def benchmark_model_get(model_db_id:int)->dict: return _j(service.db.get_model_by_id(model_db_id))
    def benchmark_model_history(model_db_id:int)->list[dict]: return _j(service.db.model_history(model_db_id))
    def _start(provider:str,mode:str):
        run=service.create_run(provider,mode,requested_by='mcp'); jobs.submit(run.id,lambda cancelled:service.execute_run(run.id,cancelled)); return {'run_id':run.id,'status':'QUEUED'}
    def benchmark_run_start(provider:str,mode:str='full')->dict: return _start(provider,mode)
    def benchmark_run_status(run_id:str)->dict: return _j(service.db.get_run(run_id))
    def benchmark_run_cancel(run_id:str)->dict: return {'run_id':run_id,'cancel_requested':jobs.cancel(run_id)}
    def benchmark_run_results(run_id:str)->dict: return _j(service.results(run_id))
    def benchmark_retest_unstable(provider:str)->dict: return _start(provider,'unstable_failed')
    def benchmark_test_new_models(provider:str,refresh:bool=True)->dict:
        if refresh: service.discover(provider)
        return _start(provider,'new')
    return {name:locals()[name] for name in MCP_TOOL_NAMES}

def build_mcp_server(service,jobs)->FastMCP:
    server=FastMCP('LLM Benchmark Manager')
    for name,fn in get_mcp_tool_functions(service,jobs).items(): server.tool(name=name)(fn)
    return server
