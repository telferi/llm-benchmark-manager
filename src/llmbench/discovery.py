from dataclasses import dataclass
from .db import Database
from .domain import ModelStatus
@dataclass(frozen=True)
class DiscoveryResult:
    new:set[str]; seen:set[str]; missing:set[str]
class DiscoveryService:
    def __init__(self,db:Database): self.db=db
    def reconcile(self,provider_id:int,discovered_ids):
        ids=set(discovered_ids); existing={m.model_id:m for m in self.db.list_models(provider_id)}; new=set()
        for mid in sorted(ids):
            old=existing.get(mid)
            if old is None: self.db.upsert_model(provider_id,mid,ModelStatus.NEW); new.add(mid)
            elif old.status==ModelStatus.MISSING: self.db.upsert_model(provider_id,mid,ModelStatus.NEW,old.metadata); new.add(mid)
            else: self.db.upsert_model(provider_id,mid,old.status,old.metadata)
        missing=set(existing)-ids
        for mid in sorted(missing):
            old=existing[mid]
            if old.status!=ModelStatus.DISABLED: self.db.set_model_status(old.id,ModelStatus.MISSING,'not returned by provider discovery')
        self.db.touch_discovery(provider_id); return DiscoveryResult(new,ids,missing)
