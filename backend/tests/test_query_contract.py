from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.routes.query import _build_confirm_reading_payload, _build_unclear_payload


CONTRACT_DIR = Path(__file__).resolve().parents[2] / "api_contract_examples"
CONTRACT_FILES = [
    "query_check_solution_correct.json",
    "query_hint.json",
    "query_reveal.json",
    "query_confirm_reading.json",
    "query_ask_clarification.json",
]


@pytest.mark.parametrize("filename", CONTRACT_FILES)
def test_query_contract_fixture_has_required_client_shape(filename: str) -> None:
    payload = json.loads((CONTRACT_DIR / filename).read_text(encoding="utf-8"))

    assert isinstance(payload["verdict"], str)
    assert isinstance(payload["response_type"], str)
    assert isinstance(payload["message_is"], str)
    assert payload["expert_mode"] in {"off", "clarity", "strict"}

    observability = payload["observability"]
    assert "traceId" in observability
    assert "requestId" in observability
    assert "clientRequestId" in observability
    assert "sessionId" in observability


def test_confirm_reading_payload_keeps_legacy_and_current_ambiguous_fields() -> None:
    regions = [{"page": 1, "snippet": "2x + ? = 11", "reason": "operator unclear"}]
    interpreted = [{"id": "reading_1", "page": 1, "label": "Step 1", "text": "2x + 3 = 11"}]

    payload = _build_confirm_reading_payload(
        ambiguous_steps=regions,
        interpreted_reading=interpreted,
        reading_confidence=0.68,
    )

    assert payload["response_type"] == "confirm_reading"
    assert payload["ambiguous_steps"] == regions
    assert payload["ambiguous_regions"] == regions
    assert payload["interpreted_reading"] == interpreted
    assert payload["reading_confidence"] == 0.68


def test_ask_clarification_payload_keeps_legacy_and_current_ambiguous_fields() -> None:
    regions = [{"page": 2, "reason": "too faint"}]

    payload = _build_unclear_payload(regions=regions)

    assert payload["response_type"] == "ask_clarification"
    assert payload["ambiguous_steps"] == regions
    assert payload["ambiguous_regions"] == regions
    assert payload["all_readable"] is False
