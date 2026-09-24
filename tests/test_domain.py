from llmbench.domain import ModelStatus, RunStatus

def test_status_values_are_stable():
    assert ModelStatus.ACTIVE.value == "ACTIVE"
    assert ModelStatus.MISSING.value == "MISSING"
    assert RunStatus.COMPLETED_WITH_ERRORS.value == "COMPLETED_WITH_ERRORS"
