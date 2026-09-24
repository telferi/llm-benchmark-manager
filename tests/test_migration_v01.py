import sqlite3
from llmbench.db import Database
from llmbench.domain import ModelStatus, ModelCapability


def test_v01_database_migrates_additively_without_rewriting_history(tmp_path):
    path = tmp_path / "legacy.db"
    c = sqlite3.connect(path)
    c.executescript("""
    PRAGMA foreign_keys=ON;
    CREATE TABLE providers(id INTEGER PRIMARY KEY,slug TEXT UNIQUE NOT NULL,name TEXT NOT NULL,provider_type TEXT NOT NULL,base_url TEXT NOT NULL,credential_source TEXT NOT NULL,credential_ref TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,last_discovery_at TEXT);
    CREATE TABLE models(id INTEGER PRIMARY KEY,provider_id INTEGER NOT NULL REFERENCES providers(id) ON DELETE CASCADE,model_id TEXT NOT NULL,status TEXT NOT NULL,first_seen_at TEXT NOT NULL,last_seen_at TEXT NOT NULL,last_success_at TEXT,last_failure_at TEXT,metadata_json TEXT NOT NULL DEFAULT '{}',UNIQUE(provider_id,model_id));
    CREATE TABLE benchmark_runs(id TEXT PRIMARY KEY,provider_id INTEGER NOT NULL REFERENCES providers(id),mode TEXT NOT NULL,status TEXT NOT NULL,benchmark_profile TEXT NOT NULL,started_at TEXT,finished_at TEXT,aiperf_version TEXT,requested_by TEXT,config_json TEXT NOT NULL DEFAULT '{}');
    CREATE TABLE benchmark_results(id INTEGER PRIMARY KEY,run_id TEXT NOT NULL REFERENCES benchmark_runs(id),model_db_id INTEGER NOT NULL REFERENCES models(id),success_count INTEGER NOT NULL,error_count INTEGER NOT NULL,success_rate REAL NOT NULL,ttft_avg REAL,ttft_p50 REAL,ttft_p90 REAL,request_latency_avg REAL,request_latency_p50 REAL,request_latency_p90 REAL,output_tokens_per_second REAL,e2e_tokens_per_second REAL,inter_token_latency REAL,request_throughput REAL,benchmark_duration REAL,raw_artifact_path TEXT,metrics_json TEXT NOT NULL DEFAULT '{}');
    CREATE TABLE errors(id INTEGER PRIMARY KEY,run_id TEXT NOT NULL REFERENCES benchmark_runs(id),model_db_id INTEGER NOT NULL REFERENCES models(id),http_status INTEGER,error_type TEXT NOT NULL,normalized_error TEXT,provider_message TEXT,count INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE model_status_history(id INTEGER PRIMARY KEY,model_db_id INTEGER NOT NULL REFERENCES models(id),old_status TEXT,new_status TEXT NOT NULL,reason TEXT,changed_at TEXT NOT NULL);
    INSERT INTO providers VALUES(1,'legacy','Legacy','openai-compatible','https://example.test','env','KEY','2026-01-01','2026-01-01',NULL);
    INSERT INTO models VALUES(1,1,'legacy/model','FAILED','2026-01-01','2026-01-01',NULL,'2026-01-01','{}');
    INSERT INTO benchmark_runs VALUES('run_legacy',1,'full','COMPLETED_WITH_ERRORS','baseline-v1','2026-01-01','2026-01-01','0.12.0','test','{}');
    INSERT INTO benchmark_results(id,run_id,model_db_id,success_count,error_count,success_rate,metrics_json) VALUES(1,'run_legacy',1,0,1,0.0,'{}');
    INSERT INTO model_status_history VALUES(1,1,'NEW','FAILED','legacy failure','2026-01-01');
    """)
    c.commit(); c.close()

    db = Database(path)
    m = db.get_model(1, "legacy/model")
    assert m.status == ModelStatus.FAILED
    assert m.capability == ModelCapability.UNKNOWN
    assert m.capability_source == "unknown"
    assert m.capability_confidence == 0.0
    assert db.get_run("run_legacy").id == "run_legacy"

    c = sqlite3.connect(path)
    assert c.execute("SELECT COUNT(*) FROM benchmark_results").fetchone()[0] == 1
    assert c.execute("SELECT COUNT(*) FROM model_status_history").fetchone()[0] == 1
    cols = {r[1] for r in c.execute("PRAGMA table_info(models)")}
    assert {"capability", "capability_source", "capability_confidence"} <= cols
    c.close()
