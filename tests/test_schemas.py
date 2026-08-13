import pytest
from pydantic import ValidationError

from nbo.schemas import BatchRequest, FeedbackRequest


def test_feedback_requires_rejection_reason():
    with pytest.raises(ValidationError):
        FeedbackRequest(decision_id="d", resultado_final="rechazada", medio_probatorio="chat_log")


def test_feedback_requires_rebate_result_when_used():
    with pytest.raises(ValidationError):
        FeedbackRequest(decision_id="d", resultado_final="aceptada", medio_probatorio="chat_log", rebate_usado=True)


def test_batch_rejects_duplicate_clients():
    with pytest.raises(ValidationError):
        BatchRequest(cliente_ids=["CLI1", "CLI1"])
