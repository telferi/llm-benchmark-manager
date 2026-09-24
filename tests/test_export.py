import json,csv
from llmbench.db import Database
from llmbench.domain import ModelStatus
from llmbench.export import export_run

def test_json_and_csv_export(tmp_path):
    db=Database(tmp_path/'d.db'); p=db.add_provider('p','P','openai-compatible','https://x','env','KEY')
    m=db.upsert_model(p.id,'m',ModelStatus.ACTIVE); run=db.create_run(p.id,'full')
    db.add_result(run.id,m.id,success_count=10,error_count=0,metrics={'ttft_p50':12.3})
    jp=export_run(db,run.id,'json',tmp_path/'o.json'); cp=export_run(db,run.id,'csv',tmp_path/'o.csv')
    assert json.loads(jp.read_text())['results'][0]['model_id']=='m'
    rows=list(csv.DictReader(cp.open())); assert rows[0]['model_id']=='m'
