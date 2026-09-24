from llmbench.db import Database
from llmbench.discovery import DiscoveryService
from llmbench.domain import ModelStatus

def test_reconciliation_tracks_new_missing_reappearing_and_disabled(tmp_path):
    db=Database(tmp_path/"x.db")
    p=db.add_provider("p","P","openai-compatible","https://x","env","KEY")
    s=DiscoveryService(db)
    r1=s.reconcile(p.id,["a","b"]); assert r1.new == {"a","b"}
    db.set_model_status(db.get_model(p.id,"a").id,ModelStatus.ACTIVE,"smoke pass")
    db.set_model_status(db.get_model(p.id,"b").id,ModelStatus.DISABLED,"owner")
    r2=s.reconcile(p.id,["a"]); assert db.get_model(p.id,"b").status == ModelStatus.DISABLED
    s.reconcile(p.id,[]); assert db.get_model(p.id,"a").status == ModelStatus.MISSING
    r4=s.reconcile(p.id,["a","b"]); assert "a" in r4.new
    assert db.get_model(p.id,"b").status == ModelStatus.DISABLED

def test_reappearing_model_records_status_history(tmp_path):
    db=Database(tmp_path/'h.db'); p=db.add_provider('p','P','openai-compatible','https://x','env','KEY'); s=DiscoveryService(db)
    s.reconcile(p.id,['a']); m=db.get_model(p.id,'a'); db.set_model_status(m.id,ModelStatus.ACTIVE,'pass')
    s.reconcile(p.id,[]); s.reconcile(p.id,['a'])
    transitions=[(x['old_status'],x['new_status']) for x in db.model_history(m.id)]
    assert ('MISSING','NEW') in transitions
