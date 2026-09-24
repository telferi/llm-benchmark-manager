from llmbench.db import Database
from llmbench.domain import ModelStatus, ModelCapability


def test_progress_counts_done_rows_not_benchmark_results(tmp_path):
    db = Database(tmp_path / "x.db")
    p = db.add_provider("p", "P", "openai-compatible", "https://example.test", "env", "KEY")
    models = [db.upsert_model(p.id, f"m{i}", ModelStatus.NEW, {}) for i in range(1, 4)]
    run = db.create_run(p.id, "full")
    db.init_run_progress(run.id, models)

    db.update_run_progress(run.id, models[0].id, stage="DONE", capability=ModelCapability.CHAT_TEXT, outcome="ACTIVE", attempt_increment=1, finished=True)
    db.update_run_progress(run.id, models[1].id, stage="SMOKE", capability=ModelCapability.EMBEDDING, attempt_increment=1)

    progress = db.get_run_progress(run.id)
    assert progress["total"] == 3
    assert progress["processed"] == 1
    assert progress["percent"] == 33.3
    assert progress["by_outcome"] == {"ACTIVE": 1}
    assert progress["current"]["model_id"] == "m2"
    assert progress["current"]["stage"] == "SMOKE"
    assert progress["current"]["capability"] == "EMBEDDING"


def test_set_model_capability_persists_source_and_confidence(tmp_path):
    db = Database(tmp_path / "x.db")
    p = db.add_provider("p", "P", "openai-compatible", "https://example.test", "env", "KEY")
    m = db.upsert_model(p.id, "embed-model", ModelStatus.NEW, {})
    m = db.set_model_capability(m.id, ModelCapability.EMBEDDING, "model_id_heuristic", 0.8)
    assert m.capability == ModelCapability.EMBEDDING
    assert m.capability_source == "model_id_heuristic"
    assert m.capability_confidence == 0.8
