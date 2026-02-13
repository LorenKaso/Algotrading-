from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.crewai_models import RiskResult


def test_risk_result_valid_literals() -> None:
    approve = RiskResult(status="APPROVE", reason="checks passed")
    veto = RiskResult(status="VETO", reason="market closed")
    assert approve.status == "APPROVE"
    assert veto.status == "VETO"


def test_risk_result_rejects_invalid_status() -> None:
    with pytest.raises(ValidationError):
        RiskResult(status="HOLD", reason="invalid")
