from __future__ import annotations
import time, httpx
from ..domain import DiscoveredModel, SmokeResult

def normalize_error(status_code:int|None,message:str=''):
    if status_code in (401,403): return ('AUTH_ERROR',False)
    if status_code==404: return ('MODEL_NOT_FOUND',False)
    if status_code==429: return ('RATE_LIMITED',True)
    if status_code==503: return ('OVERLOADED',True)
    if status_code in (500,502,504): return ('PROVIDER_ERROR',True)
    if status_code==400: return ('PAYLOAD_ERROR',False)
    if status_code is None: return ('TIMEOUT',True)
    return ('PROVIDER_ERROR', bool(status_code and status_code>=500))

class OpenAICompatibleProvider:
    def __init__(self,base_url:str,client:httpx.Client|None=None,timeout:float=30.0):
        self.base_url=base_url.rstrip('/'); self.client=client or httpx.Client(timeout=timeout)
    def _v1(self): return self.base_url if self.base_url.endswith('/v1') else self.base_url+'/v1'
    def _headers(self,key): return {'Authorization':f'Bearer {key}','Content-Type':'application/json'}
    def discover_models(self,api_key:str):
        try:r=self.client.get(self._v1()+'/models',headers=self._headers(api_key))
        except httpx.TimeoutException as e: raise RuntimeError('TIMEOUT: model discovery failed') from e
        if r.status_code>=400:
            kind,_=normalize_error(r.status_code,r.text); raise RuntimeError(f'{kind}: model discovery failed ({r.status_code})')
        payload=r.json(); data=payload.get('data',payload.get('models',[])); out=[]
        for item in data:
            if isinstance(item,str): out.append(DiscoveredModel(item,{}))
            elif item.get('id'): out.append(DiscoveredModel(str(item['id']),{k:v for k,v in item.items() if k!='id'}))
        return out
    def smoke_test(self,model_id:str,api_key:str,prompt='Say hello.',extra=None,max_tokens=16,streaming=False):
        payload={'model':model_id,'messages':[{'role':'user','content':prompt}],'max_tokens':max_tokens,'stream':streaming}
        if extra: payload.update(extra)
        t=time.perf_counter()
        try:r=self.client.post(self._v1()+'/chat/completions',headers=self._headers(api_key),json=payload)
        except httpx.TimeoutException:
            return SmokeResult(False,None,'TIMEOUT','request timed out',True,latency_ms=(time.perf_counter()-t)*1000)
        latency=(time.perf_counter()-t)*1000
        if r.status_code>=400:
            try: msg=r.json().get('error',{}).get('message',r.text)
            except Exception: msg=r.text
            kind,retry=normalize_error(r.status_code,msg); return SmokeResult(False,r.status_code,kind,msg,retry,latency_ms=latency)
        try: body=r.json(); content=body.get('choices',[{}])[0].get('message',{}).get('content')
        except Exception as e: return SmokeResult(False,r.status_code,'INVALID_RESPONSE',str(e),False,latency_ms=latency)
        if not content: return SmokeResult(False,r.status_code,'EMPTY_RESPONSE','response contained no content',False,latency_ms=latency)
        return SmokeResult(True,r.status_code,content=content,latency_ms=latency)
