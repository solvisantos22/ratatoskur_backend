from __future__ import annotations

import base64
import json
from io import BytesIO

import pytest
from PIL import Image

from backend.exam_service import extract_answer_text_from_image


def _png_base64(*, width: int = 24, height: int = 24) -> str:
    image = Image.new("RGB", (width, height), "white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def test_extract_answer_text_from_image_uses_shared_llm_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    import backend.llm as llm

    captured: dict[str, object] = {}

    def fake_extract(*, prompt: str, answer_image: Image.Image, request_id: str | None = None) -> dict[str, object]:
        captured["prompt"] = prompt
        captured["size"] = answer_image.size
        return {"response_text": json.dumps({"answer_text": "x = 4"})}

    monkeypatch.setattr(llm, "call_exam_answer_extraction_with_retry", fake_extract)

    answer = extract_answer_text_from_image(
        answer_image_base64=_png_base64(),
        question_text="Solve x + 1 = 5",
        answer_format="numeric",
    )

    assert answer == "4"
    assert "Solve x + 1 = 5" in str(captured["prompt"])
    assert captured["size"] == (24, 24)


def test_extract_answer_text_from_image_returns_none_for_unreadable(monkeypatch: pytest.MonkeyPatch) -> None:
    import backend.llm as llm

    monkeypatch.setattr(
        llm,
        "call_exam_answer_extraction_with_retry",
        lambda **_: {"response_text": json.dumps({"answer_text": None})},
    )

    answer = extract_answer_text_from_image(
        answer_image_base64=_png_base64(),
        question_text="Solve x + 1 = 5",
        answer_format="numeric",
    )

    assert answer is None


def test_extract_answer_text_from_image_rejects_oversized_image() -> None:
    with pytest.raises(ValueError, match="dimensions are too large"):
        extract_answer_text_from_image(
            answer_image_base64=_png_base64(width=2049, height=24),
            question_text="Solve x + 1 = 5",
            answer_format="numeric",
        )


def test_extract_answer_text_from_image_rejects_malformed_model_json(monkeypatch: pytest.MonkeyPatch) -> None:
    import backend.llm as llm

    monkeypatch.setattr(
        llm,
        "call_exam_answer_extraction_with_retry",
        lambda **_: {"response_text": "{not-json"},
    )

    with pytest.raises(json.JSONDecodeError):
        extract_answer_text_from_image(
            answer_image_base64=_png_base64(),
            question_text="Solve x + 1 = 5",
            answer_format="numeric",
        )
