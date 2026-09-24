from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, Future
from threading import Event, Lock
from typing import Callable, Any

class LocalJobManager:
    def __init__(self,max_workers:int=2):
        self._pool=ThreadPoolExecutor(max_workers=max_workers,thread_name_prefix='llmbench')
        self._futures:dict[str,Future]={}; self._cancel:dict[str,Event]={}; self._lock=Lock()
    def submit(self,run_id:str,fn:Callable[[Callable[[],bool]],Any])->str:
        event=Event()
        def wrapped(): return fn(event.is_set)
        with self._lock:
            if run_id in self._futures and not self._futures[run_id].done(): raise ValueError(f'job already running: {run_id}')
            self._cancel[run_id]=event; self._futures[run_id]=self._pool.submit(wrapped)
        return run_id
    def cancel(self,run_id:str)->bool:
        with self._lock:
            event=self._cancel.get(run_id); future=self._futures.get(run_id)
        if event is None: return False
        event.set()
        if future is not None: future.cancel()
        return True
    def wait(self,run_id:str,timeout:float|None=None):
        with self._lock: future=self._futures.get(run_id)
        if future is None: raise KeyError(run_id)
        if future.cancelled(): return None
        return future.result(timeout=timeout)
    def done(self,run_id:str)->bool:
        with self._lock: f=self._futures.get(run_id)
        return bool(f and f.done())
    def shutdown(self,wait=True): self._pool.shutdown(wait=wait,cancel_futures=False)
