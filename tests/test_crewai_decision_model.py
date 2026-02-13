from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.crewai_models import DecisionModel


def test_decision_model_valid() -> None:
    model = DecisionModel(action="BUY", symbol="PLTR", reason="test")
    assert model.action == "BUY"
    assert model.symbol == "PLTR"
    assert model.reason == "test"


def test_decision_model_rejects_invalid_action() -> None:
    with pytest.raises(ValidationError):
        DecisionModel(action="APPROVE", symbol=None, reason="bad")
