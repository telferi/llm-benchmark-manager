from llmbench.db import Database
from llmbench.domain import ModelStatus

def test_provider_and_model_round_trip(tmp_path):
    db=Database(tmp_path/"x.db")
    p=db.add_provider("nvidia","NVIDIA","openai-compatible","https://example.test","env","NVIDIA_API_KEY")
    assert db.get_provider(p.id).credential_ref == "NVIDIA_API_KEY"
    assert [x.slug for x in db.list_providers()] == ["nvidia"]
    m1=db.upsert_model(p.id,"model-a",ModelStatus.NEW,{"owner":"nvidia"})
    first=m1.first_seen_at
    m2=db.upsert_model(p.id,"model-a",ModelStatus.ACTIVE,{"owner":"nvidia"})
    assert m2.id == m1.id
    assert m2.first_seen_at == first
    assert m2.status == ModelStatus.ACTIVE


def test_v02_statuses_and_capabilities_exist():
    from llmbench.domain import ModelStatus, ModelCapability
    assert ModelStatus.NOT_AVAILABLE.value == "NOT_AVAILABLE"
    assert ModelStatus.INCOMPATIBLE.value == "INCOMPATIBLE"
    assert ModelCapability.CHAT_TEXT.value == "CHAT_TEXT"
    assert ModelCapability.EMBEDDING.value == "EMBEDDING"
    assert ModelCapability.UNKNOWN.value == "UNKNOWN"
