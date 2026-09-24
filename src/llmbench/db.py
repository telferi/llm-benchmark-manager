from __future__ import annotations
import json, sqlite3, uuid
from pathlib import Path
from datetime import datetime, timezone
from .domain import Provider, ModelRecord, ModelStatus, BenchmarkRun, RunStatus

def utcnow()->str: return datetime.now(timezone.utc).isoformat()

class Database:
    def __init__(self,path:str|Path):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True); self._migrate()
    def _connect(self):
        c=sqlite3.connect(self.path); c.row_factory=sqlite3.Row; c.execute('PRAGMA foreign_keys=ON'); return c
    def _migrate(self):
        with self._connect() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS providers(id INTEGER PRIMARY KEY,slug TEXT UNIQUE NOT NULL,name TEXT NOT NULL,provider_type TEXT NOT NULL,base_url TEXT NOT NULL,credential_source TEXT NOT NULL,credential_ref TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,last_discovery_at TEXT);
            CREATE TABLE IF NOT EXISTS models(id INTEGER PRIMARY KEY,provider_id INTEGER NOT NULL REFERENCES providers(id) ON DELETE CASCADE,model_id TEXT NOT NULL,status TEXT NOT NULL,first_seen_at TEXT NOT NULL,last_seen_at TEXT NOT NULL,last_success_at TEXT,last_failure_at TEXT,metadata_json TEXT NOT NULL DEFAULT '{}',UNIQUE(provider_id,model_id));
            CREATE TABLE IF NOT EXISTS benchmark_runs(id TEXT PRIMARY KEY,provider_id INTEGER NOT NULL REFERENCES providers(id),mode TEXT NOT NULL,status TEXT NOT NULL,benchmark_profile TEXT NOT NULL,started_at TEXT,finished_at TEXT,aiperf_version TEXT,requested_by TEXT,config_json TEXT NOT NULL DEFAULT '{}');
            CREATE TABLE IF NOT EXISTS benchmark_results(id INTEGER PRIMARY KEY,run_id TEXT NOT NULL REFERENCES benchmark_runs(id),model_db_id INTEGER NOT NULL REFERENCES models(id),success_count INTEGER NOT NULL,error_count INTEGER NOT NULL,success_rate REAL NOT NULL,ttft_avg REAL,ttft_p50 REAL,ttft_p90 REAL,request_latency_avg REAL,request_latency_p50 REAL,request_latency_p90 REAL,output_tokens_per_second REAL,e2e_tokens_per_second REAL,inter_token_latency REAL,request_throughput REAL,benchmark_duration REAL,raw_artifact_path TEXT,metrics_json TEXT NOT NULL DEFAULT '{}');
            CREATE TABLE IF NOT EXISTS errors(id INTEGER PRIMARY KEY,run_id TEXT NOT NULL REFERENCES benchmark_runs(id),model_db_id INTEGER NOT NULL REFERENCES models(id),http_status INTEGER,error_type TEXT NOT NULL,normalized_error TEXT,provider_message TEXT,count INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS model_status_history(id INTEGER PRIMARY KEY,model_db_id INTEGER NOT NULL REFERENCES models(id),old_status TEXT,new_status TEXT NOT NULL,reason TEXT,changed_at TEXT NOT NULL);
            ''')
    def _provider(self,r): return Provider(r['id'],r['slug'],r['name'],r['provider_type'],r['base_url'],r['credential_source'],r['credential_ref'],r['created_at'],r['updated_at'],r['last_discovery_at'])
    def _model(self,r): return ModelRecord(r['id'],r['provider_id'],r['model_id'],ModelStatus(r['status']),r['first_seen_at'],r['last_seen_at'],r['last_success_at'],r['last_failure_at'],json.loads(r['metadata_json'] or '{}'))
    def add_provider(self,slug,name,provider_type,base_url,credential_source='env',credential_ref=''):
        now=utcnow()
        with self._connect() as c:
            cur=c.execute('INSERT INTO providers(slug,name,provider_type,base_url,credential_source,credential_ref,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',(slug,name,provider_type,base_url.rstrip('/'),credential_source,credential_ref,now,now)); pid=cur.lastrowid
        return self.get_provider(pid)
    def get_provider(self,provider_id:int):
        with self._connect() as c:r=c.execute('SELECT * FROM providers WHERE id=?',(provider_id,)).fetchone()
        if not r: raise KeyError(f'provider {provider_id} not found')
        return self._provider(r)
    def get_provider_by_slug(self,slug:str):
        with self._connect() as c:r=c.execute('SELECT * FROM providers WHERE slug=?',(slug,)).fetchone()
        if not r: raise KeyError(f'provider {slug} not found')
        return self._provider(r)
    def list_providers(self):
        with self._connect() as c: rows=c.execute('SELECT * FROM providers ORDER BY id').fetchall()
        return [self._provider(r) for r in rows]
    def touch_discovery(self,provider_id:int):
        now=utcnow()
        with self._connect() as c:c.execute('UPDATE providers SET last_discovery_at=?,updated_at=? WHERE id=?',(now,now,provider_id))
    def upsert_model(self,provider_id:int,model_id:str,status:ModelStatus,metadata=None):
        now=utcnow(); meta=json.dumps(metadata or {},sort_keys=True)
        with self._connect() as c:
            r=c.execute('SELECT * FROM models WHERE provider_id=? AND model_id=?',(provider_id,model_id)).fetchone()
            if r:
                c.execute('UPDATE models SET status=?,last_seen_at=?,metadata_json=? WHERE id=?',(status.value,now,meta,r['id']))
                if r['status']!=status.value:
                    c.execute('INSERT INTO model_status_history(model_db_id,old_status,new_status,reason,changed_at) VALUES(?,?,?,?,?)',(r['id'],r['status'],status.value,'upsert status change',now))
            else:
                cur=c.execute('INSERT INTO models(provider_id,model_id,status,first_seen_at,last_seen_at,metadata_json) VALUES(?,?,?,?,?,?)',(provider_id,model_id,status.value,now,now,meta))
                c.execute('INSERT INTO model_status_history(model_db_id,old_status,new_status,reason,changed_at) VALUES(?,?,?,?,?)',(cur.lastrowid,None,status.value,'discovered',now))
        return self.get_model(provider_id,model_id)
    def get_model(self,provider_id:int,model_id:str):
        with self._connect() as c:r=c.execute('SELECT * FROM models WHERE provider_id=? AND model_id=?',(provider_id,model_id)).fetchone()
        if not r: raise KeyError(f'model {model_id} not found')
        return self._model(r)
    def get_model_by_id(self,model_db_id:int):
        with self._connect() as c:r=c.execute('SELECT * FROM models WHERE id=?',(model_db_id,)).fetchone()
        if not r: raise KeyError(f'model {model_db_id} not found')
        return self._model(r)
    def list_models(self,provider_id:int,statuses=None):
        args=[provider_id]; sql='SELECT * FROM models WHERE provider_id=?'
        if statuses:
            vals=[s.value if isinstance(s,ModelStatus) else str(s) for s in statuses]
            sql+=' AND status IN ('+','.join('?' for _ in vals)+')'; args+=vals
        sql+=' ORDER BY model_id'
        with self._connect() as c: rows=c.execute(sql,args).fetchall()
        return [self._model(r) for r in rows]
    def set_model_status(self,model_db_id:int,status:ModelStatus,reason:str=''):
        now=utcnow()
        with self._connect() as c:
            r=c.execute('SELECT status FROM models WHERE id=?',(model_db_id,)).fetchone()
            if not r: raise KeyError(model_db_id)
            old=r['status']; success=now if status==ModelStatus.ACTIVE else None; failure=now if status in (ModelStatus.UNSTABLE,ModelStatus.FAILED,ModelStatus.UNSUPPORTED) else None
            c.execute('UPDATE models SET status=?,last_success_at=COALESCE(?,last_success_at),last_failure_at=COALESCE(?,last_failure_at) WHERE id=?',(status.value,success,failure,model_db_id))
            if old!=status.value:c.execute('INSERT INTO model_status_history(model_db_id,old_status,new_status,reason,changed_at) VALUES(?,?,?,?,?)',(model_db_id,old,status.value,reason,now))
        return self.get_model_by_id(model_db_id)
    def create_run(self,provider_id:int,mode:str,profile='baseline-v1',requested_by='cli',config=None,run_id=None):
        rid=run_id or 'run_'+uuid.uuid4().hex[:16]
        with self._connect() as c:c.execute('INSERT INTO benchmark_runs(id,provider_id,mode,status,benchmark_profile,requested_by,config_json) VALUES(?,?,?,?,?,?,?)',(rid,provider_id,mode,RunStatus.QUEUED.value,profile,requested_by,json.dumps(config or {},sort_keys=True)))
        return self.get_run(rid)
    def update_run_status(self,run_id,status:RunStatus,aiperf_version=None):
        now=utcnow(); start=now if status==RunStatus.RUNNING else None; finish=now if status in (RunStatus.COMPLETED,RunStatus.COMPLETED_WITH_ERRORS,RunStatus.FAILED,RunStatus.CANCELLED) else None
        with self._connect() as c:c.execute('UPDATE benchmark_runs SET status=?,started_at=COALESCE(started_at,?),finished_at=COALESCE(?,finished_at),aiperf_version=COALESCE(?,aiperf_version) WHERE id=?',(status.value,start,finish,aiperf_version,run_id))
        return self.get_run(run_id)
    def get_run(self,run_id):
        with self._connect() as c:r=c.execute('SELECT * FROM benchmark_runs WHERE id=?',(run_id,)).fetchone()
        if not r: raise KeyError(run_id)
        return BenchmarkRun(r['id'],r['provider_id'],r['mode'],RunStatus(r['status']),r['benchmark_profile'],r['started_at'],r['finished_at'],r['aiperf_version'],r['requested_by'],json.loads(r['config_json'] or '{}'))
    def add_result(self,run_id,model_db_id,*,success_count,error_count,metrics,raw_artifact_path=None):
        total=success_count+error_count; rate=(success_count/total*100.0) if total else 0.0; g=lambda k:metrics.get(k)
        with self._connect() as c:c.execute('''INSERT INTO benchmark_results(run_id,model_db_id,success_count,error_count,success_rate,ttft_avg,ttft_p50,ttft_p90,request_latency_avg,request_latency_p50,request_latency_p90,output_tokens_per_second,e2e_tokens_per_second,inter_token_latency,request_throughput,benchmark_duration,raw_artifact_path,metrics_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(run_id,model_db_id,success_count,error_count,rate,g('ttft_avg'),g('ttft_p50'),g('ttft_p90'),g('latency_avg'),g('latency_p50'),g('latency_p90'),g('output_tokens_per_second'),g('e2e_tokens_per_second'),g('inter_token_latency'),g('request_throughput'),g('benchmark_duration'),str(raw_artifact_path) if raw_artifact_path else None,json.dumps(metrics,sort_keys=True)))
    def add_error(self,run_id,model_db_id,error_type,message='',http_status=None,count=1,normalized_error=None):
        with self._connect() as c:c.execute('INSERT INTO errors(run_id,model_db_id,http_status,error_type,normalized_error,provider_message,count) VALUES(?,?,?,?,?,?,?)',(run_id,model_db_id,http_status,error_type,normalized_error or error_type,message,count))
    def get_results(self,run_id):
        with self._connect() as c:
            rows=c.execute('SELECT r.*,m.model_id FROM benchmark_results r JOIN models m ON m.id=r.model_db_id WHERE run_id=? ORDER BY r.id',(run_id,)).fetchall()
            errs=c.execute('SELECT e.*,m.model_id FROM errors e JOIN models m ON m.id=e.model_db_id WHERE run_id=? ORDER BY e.id',(run_id,)).fetchall()
        return {'results':[dict(r) for r in rows],'errors':[dict(e) for e in errs]}
    def model_history(self,model_db_id):
        with self._connect() as c: rows=c.execute('SELECT * FROM model_status_history WHERE model_db_id=? ORDER BY id',(model_db_id,)).fetchall()
        return [dict(r) for r in rows]
