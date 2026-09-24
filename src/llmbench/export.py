from __future__ import annotations
import csv,json
from pathlib import Path

def export_run(db,run_id:str,fmt:str,path:str|Path)->Path:
    p=Path(path); p.parent.mkdir(parents=True,exist_ok=True); data=db.get_results(run_id); fmt=fmt.lower()
    if fmt=='json': p.write_text(json.dumps(data,indent=2,sort_keys=True,default=str)); return p
    if fmt=='csv':
        rows=data['results']; fields=sorted({k for r in rows for k in r}) if rows else ['model_id']
        with p.open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)
        return p
    raise ValueError('format must be json or csv')
