from __future__ import annotations
from dataclasses import asdict
from enum import Enum
from typing import Any
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

class ProviderCreate(BaseModel):
    slug:str=Field(min_length=1,pattern=r'^[A-Za-z0-9._-]+$')
    name:str=Field(min_length=1)
    provider_type:str='openai-compatible'
    base_url:str=Field(min_length=4)
    credential_env:str=Field(min_length=1,pattern=r'^[A-Za-z_][A-Za-z0-9_]*$')
class RunCreate(BaseModel):
    provider:str|int
    mode:str='full'

def _jsonable(v:Any):
    if isinstance(v,Enum): return v.value
    if hasattr(v,'__dataclass_fields__'): return _jsonable(asdict(v))
    if isinstance(v,dict): return {k:_jsonable(x) for k,x in v.items()}
    if isinstance(v,(list,tuple,set)): return [_jsonable(x) for x in v]
    return v

def create_app(service,jobs):
    app=FastAPI(title='LLM Benchmark Manager',version='0.1.0')
    @app.get('/api/v1/providers')
    def providers(): return [_jsonable(service.provider_view(p)) for p in service.list_providers()]
    @app.post('/api/v1/providers',status_code=201)
    def provider_create(body:ProviderCreate):
        try: p=service.add_provider(body.slug,body.name,body.provider_type,body.base_url,body.credential_env); return _jsonable(service.provider_view(p))
        except Exception as e: raise HTTPException(400,str(e))
    @app.get('/api/v1/providers/{provider_id}')
    def provider_get(provider_id:str):
        try:return _jsonable(service.provider_view(service.resolve_provider(provider_id)))
        except KeyError as e: raise HTTPException(404,str(e))
    @app.post('/api/v1/providers/{provider_id}/discover')
    def provider_discover(provider_id:str):
        try:return _jsonable(service.discover(provider_id))
        except KeyError as e: raise HTTPException(404,str(e))
        except Exception as e: raise HTTPException(400,str(e))
    @app.get('/api/v1/providers/{provider_id}/models')
    def provider_models(provider_id:str):
        try:p=service.resolve_provider(provider_id); return [_jsonable(m) for m in service.db.list_models(p.id)]
        except KeyError as e: raise HTTPException(404,str(e))
    @app.post('/api/v1/runs',status_code=202)
    def run_create(body:RunCreate):
        try: run=service.create_run(body.provider,body.mode,requested_by='api'); jobs.submit(run.id,lambda cancelled:service.execute_run(run.id,cancelled)); return {'run_id':run.id,'status':'queued'}
        except Exception as e: raise HTTPException(400,str(e))
    @app.get('/api/v1/runs/{run_id}')
    def run_get(run_id:str):
        try:return _jsonable(service.db.get_run(run_id))
        except KeyError as e: raise HTTPException(404,str(e))
    @app.post('/api/v1/runs/{run_id}/cancel')
    def run_cancel(run_id:str):
        if not jobs.cancel(run_id): raise HTTPException(404,'job not found')
        return {'run_id':run_id,'cancel_requested':True}
    @app.get('/api/v1/runs/{run_id}/results')
    def run_results(run_id:str):
        try: service.db.get_run(run_id); return _jsonable(service.results(run_id))
        except KeyError as e: raise HTTPException(404,str(e))
    @app.get('/api/v1/models/{model_db_id}')
    def model_get(model_db_id:int):
        try:return _jsonable(service.db.get_model_by_id(model_db_id))
        except KeyError as e: raise HTTPException(404,str(e))
    @app.get('/api/v1/models/{model_db_id}/history')
    def model_history(model_db_id:int):
        try: service.db.get_model_by_id(model_db_id); return _jsonable(service.db.model_history(model_db_id))
        except KeyError as e: raise HTTPException(404,str(e))
    return app
