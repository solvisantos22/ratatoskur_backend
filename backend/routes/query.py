from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from PIL import Image, ImageDraw, UnidentifiedImageError
from sqlmodel import Session, select

from backend.auth.deps import get_current_user
from backend.config import QUERY_MAX_PAGE_COUNT, QUERY_MAX_SINGLE_FILE_BYTES, QUERY_MAX_TOTAL_BYTES
from backend.db import engine, get_session
from backend.error_taxonomy import normalize_error_type
from backend.llm import call_deferred_error_with_retry, call_legibility_with_retry, call_mode_v3_with_retry
from backend.models.auth_models import (
    AnalyticsEvent,
    Attempt,
    AttemptStageMetric,
    ErrorBankEntry,
    ErrorEvent,
    Problem,
    User,
)
from backend.storage.r2 import R2ConfigurationError, upload_bytes

router = APIRouter(tags=["query"])

PROMPTS_BASE = Path(__file__).resolve().parents[1] / "prompts"
PROMPTS_ROOT = PROMPTS_BASE / "modes"
PROMPTS_EXPERT_ROOT = PROMPTS_BASE / "modes_expert"
LEGIBILITY_PROMPT_ROOT = PROMPTS_BASE / "legibility"
ERROR_PROMPT_PATH_V4 = PROMPTS_BASE / "errors" / "v4" / "prompt.txt"
DEFAULT_MODE_PROMPT_VARIANT = (os.getenv("QUERY_PROMPT_VARIANT") or "v6").strip().lower()
DEFAULT_EXPERT_MODE_PROMPT_VARIANT = (os.getenv("QUERY_EXPERT_PROMPT_VARIANT") or "v4").strip().lower()
DEFAULT_LEGIBILITY_PROMPT_VARIANT = (os.getenv("QUERY_LEGIBILITY_PROMPT_VARIANT") or "v4").strip().lower()
ExpertMode = Literal["off", "clarity", "strict"]
SUCCESS_VERDICTS = {"correct_so_far", "fully_correct", "fully_solved"}
READING_CONFIRM_CONFIDENCE_MIN = 0.30
QUERY_MAX_IMAGE_PIXELS = int(os.getenv("QUERY_MAX_IMAGE_PIXELS", str(16_000_000)))
LEGIBILITY_MAX_IMAGE_SIDE = int(os.getenv("LEGIBILITY_MAX_IMAGE_SIDE", "1600"))


def _resolve_mode_prompt_variant() -> Literal["v1", "v2", "v3", "v4", "v5", "v6"]:
    configured = (os.getenv("QUERY_PROMPT_VARIANT") or DEFAULT_MODE_PROMPT_VARIANT).strip().lower()
    if configured == "v1":
        return "v1"
    if configured == "v2":
        return "v2"
    if configured == "v3":
        return "v3"
    if configured == "v4":
        return "v4"
    if configured == "v5":
        return "v5"
    return "v6"


def _resolve_legibility_prompt_variant() -> Literal["v2", "v3", "v4"]:
    configured = (os.getenv("QUERY_LEGIBILITY_PROMPT_VARIANT") or DEFAULT_LEGIBILITY_PROMPT_VARIANT).strip().lower()
    if configured == "v2":
        return "v2"
    if configured == "v3":
        return "v3"
    return "v4"


def _resolve_expert_mode_prompt_variant() -> Literal["v2", "v3", "v4"]:
    configured = (os.getenv("QUERY_EXPERT_PROMPT_VARIANT") or DEFAULT_EXPERT_MODE_PROMPT_VARIANT).strip().lower()
    if configured == "v2":
        return "v2"
    if configured == "v3":
        return "v3"
    return "v4"


def _resolve_pipeline_mode(value: str | None) -> Literal["single_pass", "two_pass"]:
    configured = (value or "two_pass").strip().lower()
    if configured == "single_pass":
        return "single_pass"
    return "two_pass"


def _normalize_expert_mode(value: str | None) -> ExpertMode:
    normalized = (value or "off").strip().lower()
    if normalized == "clarity":
        return "clarity"
    if normalized == "strict":
        return "strict"
    return "off"


def _load_prompt(
    mode: Literal["hint", "check_solution", "reveal"],
    *,
    prompt_variant: Literal["v1", "v2", "v3", "v4", "v5", "v6"],
    expert_prompt_variant: Literal["v2", "v3", "v4"],
    expert_mode: ExpertMode,
) -> str:
    prompt_path = _resolve_mode_prompt_path(
        mode=mode,
        prompt_variant=prompt_variant,
        expert_prompt_variant=expert_prompt_variant,
        expert_mode=expert_mode,
    )
    try:
        return prompt_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Prompt file not found for mode '{mode}' in variant '{prompt_variant}'",
        ) from exc


def _resolve_mode_prompt_path(
    *,
    mode: Literal["hint", "check_solution", "reveal"],
    prompt_variant: Literal["v1", "v2", "v3", "v4", "v5", "v6"],
    expert_prompt_variant: Literal["v2", "v3", "v4"],
    expert_mode: ExpertMode,
) -> Path:
    if mode == "check_solution" and expert_mode != "off":
        expert_prompt_path = PROMPTS_EXPERT_ROOT / expert_prompt_variant / expert_mode / mode / "prompt.txt"
        if expert_prompt_path.exists():
            return expert_prompt_path

    return PROMPTS_ROOT / prompt_variant / mode / "prompt.txt"


def _load_legibility_prompt(*, prompt_variant: Literal["v2", "v3", "v4"]) -> str:
    prompt_path = LEGIBILITY_PROMPT_ROOT / prompt_variant / "prompt.txt"
    try:
        return prompt_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail="Legibility prompt file not found") from exc


def _load_deferred_error_prompt() -> str:
    try:
        return ERROR_PROMPT_PATH_V4.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail="Deferred error prompt file not found") from exc


def _augment_prompt_for_pages(*, base_prompt: str, page_count: int) -> str:
    return (
        f"{base_prompt}\n\n"
        "MULTI-PAGE CONTEXT:\n"
        f"- You receive {page_count} solution page image(s), in strict page order from 1 to {page_count}.\n"
        "- Analyze pages sequentially from earliest to latest.\n"
        "- If there is an error or unclear handwriting, identify where it FIRST appears.\n"
        "- In message_is, explicitly mention that page number when identifiable.\n"
    )


def _as_bool_or_none(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    return None


def _coerce_legibility_regions(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []

    regions: list[dict[str, object]] = []
    for item in value[:8]:
        if not isinstance(item, dict):
            continue
        page = _as_int_or_none(item.get("page"))
        if page is not None:
            page = max(1, min(page, QUERY_MAX_PAGE_COUNT))
        snippet = _text_or_none(item.get("snippet"), max_len=120)
        reason = _text_or_none(item.get("reason"), max_len=160)
        if page is None and snippet is None and reason is None:
            continue

        normalized_region: dict[str, object] = {}
        if page is not None:
            normalized_region["page"] = page
        if snippet is not None:
            normalized_region["snippet"] = snippet
        if reason is not None:
            normalized_region["reason"] = reason
        regions.append(normalized_region)
    return regions


def _evaluate_legibility_payload(
    payload: dict[str, object],
    *,
    fail_closed: bool,
) -> tuple[bool, bool | None, list[dict[str, object]]]:
    all_readable = _as_bool_or_none(payload.get("all_readable"))
    regions = _coerce_legibility_regions(payload.get("ambiguous_steps"))
    failed = bool(regions) or all_readable is False
    if fail_closed and all_readable is None:
        failed = True
    return failed, all_readable, regions


def _build_unclear_payload(
    *,
    regions: list[dict[str, object]],
) -> dict[str, object]:
    if regions:
        parts: list[str] = []
        for region in regions[:2]:
            page = region.get("page")
            reason = _text_or_none(region.get("reason"), max_len=120)
            snippet = _text_or_none(region.get("snippet"), max_len=80)
            detail = reason or snippet or "hluti úr lausninni er óskýr"
            if page is not None:
                parts.append(f"bls. {page}: {detail}")
            else:
                parts.append(detail)
        details = "; ".join(parts)
        message = (
            f"Ég get ekki lesið lausnina nægilega skýrt ({details}). "
            "Vinsamlegast skrifaðu þessi skref skýrar og sendu aftur."
        )
    else:
        message = (
            "Ég get ekki staðfest lausnina því skriftin er ólæsileg á mikilvægum stöðum. "
            "Vinsamlegast skrifaðu skrefin skýrar og sendu aftur."
        )

    return {
        "verdict": "unclear",
        "response_type": "ask_clarification",
        "message_is": message,
        "error_type": "",
        "error_step": "",
        "correct_approach": "",
        "error_confidence": None,
        "all_readable": False,
        "ambiguous_steps": regions,
        "ambiguous_regions": regions,
    }


def _to_pil_image(upload: UploadFile, data: bytes) -> Image.Image:
    try:
        image = Image.open(BytesIO(data))
        image.load()
        _validate_image_dimensions(image, filename=upload.filename or "upload")
        return image
    except UnidentifiedImageError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid image uploaded for field '{upload.filename}'",
        ) from exc


def _bytes_to_pil_image(data: bytes, *, filename: str) -> Image.Image:
    try:
        image = Image.open(BytesIO(data))
        image.load()
        _validate_image_dimensions(image, filename=filename)
        return image
    except UnidentifiedImageError as exc:
        raise ValueError(f"Invalid image bytes for '{filename}'") from exc


def _validate_image_dimensions(image: Image.Image, *, filename: str) -> None:
    width, height = image.size
    if width <= 0 or height <= 0:
        raise HTTPException(status_code=422, detail=f"Invalid image dimensions for '{filename}'")
    if width * height > QUERY_MAX_IMAGE_PIXELS:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Image '{filename}' is too large in pixel dimensions. "
                "Try a lower-resolution export or fewer pages."
            ),
        )


def _downscale_for_legibility(image: Image.Image) -> Image.Image:
    downscaled = image.copy()
    downscaled.thumbnail((LEGIBILITY_MAX_IMAGE_SIDE, LEGIBILITY_MAX_IMAGE_SIDE), Image.Resampling.LANCZOS)
    if downscaled.mode not in {"RGB", "RGBA"}:
        downscaled = downscaled.convert("RGB")
    return downscaled


def _safe_suffix(upload: UploadFile, default: str) -> str:
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix and len(suffix) <= 10:
        return suffix
    return default


def _text_or_none(value: object, max_len: int | None = None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if max_len is not None:
        return text[:max_len]
    return text


def _record_event(
    *,
    session: Session,
    user_id: UUID,
    problem_id: UUID,
    attempt_id: UUID | None,
    event_type: str,
    mode: str,
    verdict: str | None = None,
    metadata_json: str | None = None,
) -> None:
    session.add(
        AnalyticsEvent(
            id=uuid4(),
            user_id=user_id,
            problem_id=problem_id,
            attempt_id=attempt_id,
            event_type=event_type,
            mode=mode,
            verdict=verdict,
            metadata_json=metadata_json,
            created_at=datetime.now(timezone.utc),
        )
    )


def _as_int_or_none(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed < 0.0:
        return 0.0
    if parsed > 1.0:
        return 1.0
    return parsed


def _coerce_confirmed_reading_entries(
    value: object,
    *,
    page_count: int,
) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []

    entries: list[dict[str, object]] = []
    for index, item in enumerate(value[:16], start=1):
        if not isinstance(item, dict):
            continue
        text = _text_or_none(item.get("text"), max_len=400)
        if not text:
            continue
        page = _as_int_or_none(item.get("page"))
        if page is not None:
            page = max(1, min(page, page_count))
        label = _text_or_none(item.get("label"), max_len=80) or (
            f"Bls. {page}" if page is not None else f"Skref {index}"
        )
        entries.append(
            {
                "id": _text_or_none(item.get("id"), max_len=64) or f"reading_{index}",
                "page": page,
                "label": label,
                "text": text,
            }
        )
    return entries


def _parse_confirmed_reading_json(
    raw_value: str | None,
    *,
    page_count: int,
) -> list[dict[str, object]]:
    text = _text_or_none(raw_value, max_len=20_000)
    if not text:
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"confirmed_reading_json is invalid JSON: {exc}") from exc
    entries = _coerce_confirmed_reading_entries(payload, page_count=page_count)
    if not entries:
        raise HTTPException(status_code=422, detail="confirmed_reading_json must contain at least one entry with text")
    return entries


def _augment_prompt_with_confirmed_reading(
    *,
    base_prompt: str,
    confirmed_entries: list[dict[str, object]],
) -> str:
    if not confirmed_entries:
        return base_prompt

    lines = [
        "",
        "USER-CONFIRMED READING:",
        "- The student has reviewed and corrected uncertain handwriting.",
        "- Treat these entries as authoritative transcription for ambiguous regions.",
    ]
    for entry in confirmed_entries:
        page = entry.get("page")
        label = _text_or_none(entry.get("label"), max_len=80) or "Skref"
        text = _text_or_none(entry.get("text"), max_len=400) or ""
        if page is not None:
            lines.append(f"- bls. {page} ({label}): {text}")
        else:
            lines.append(f"- {label}: {text}")
    return base_prompt + "\n".join(lines)


def _augment_deferred_error_prompt(*, base_prompt: str, message_is: str) -> str:
    safe_message = _text_or_none(message_is, max_len=2_000) or ""
    return (
        f"{base_prompt}\n\n"
        "FAST USER-FACING FEEDBACK:\n"
        f"- message_is: {safe_message}\n"
    )


def _build_ambiguous_step_entries(
    *,
    page_count: int,
    ambiguous_steps: list[dict[str, object]],
) -> list[dict[str, object]]:
    fallback_entries: list[dict[str, object]] = []
    for index, region in enumerate(ambiguous_steps[:8], start=1):
        if not isinstance(region, dict):
            continue
        snippet = _text_or_none(region.get("snippet"), max_len=160)
        reason = _text_or_none(region.get("reason"), max_len=160)
        if not snippet and not reason:
            continue
        page = _as_int_or_none(region.get("page"))
        if page is not None:
            page = max(1, min(page, page_count))
        text = snippet or reason or ""
        fallback_entries.append(
            {
                "id": f"reading_{index}",
                "page": page,
                "label": f"Óskýrt skref á bls. {page}" if page is not None else f"Óskýrt skref {index}",
                "text": text,
            }
        )
    return fallback_entries


def _build_confirm_reading_payload(
    *,
    ambiguous_steps: list[dict[str, object]],
    interpreted_reading: list[dict[str, object]],
    reading_confidence: float | None,
) -> dict[str, object]:
    confidence_value = reading_confidence if reading_confidence is not None else 0.5
    message = "Ég er ekki alveg viss um lesturinn á sumum skrefum. Vinsamlegast staðfestu eða leiðréttu aðeins þessi óskýru skref áður en ég met lausnina."
    return {
        "verdict": "unclear",
        "response_type": "confirm_reading",
        "message_is": message,
        "error_type": "",
        "error_step": "",
        "correct_approach": "",
        "error_confidence": None,
        "all_readable": False,
        "reading_confidence": confidence_value,
        "interpreted_reading": interpreted_reading,
        "ambiguous_steps": ambiguous_steps,
        "ambiguous_regions": ambiguous_steps,
    }


def _extract_llm_result(
    result: object,
    *,
    default_request_id: str,
) -> tuple[
    str,
    str | None,
    float | None,
    int | None,
    int | None,
    int | None,
    int | None,
    str | None,
    str | None,
    str | None,
    str,
    int | None,
    str | None,
    int | None,
    bool | None,
]:
    if isinstance(result, dict):
        resp_text = result.get("response_text")
        model_name = _text_or_none(result.get("model_name"), max_len=128)
        latency_seconds = float(result["latency_seconds"]) if result.get("latency_seconds") is not None else None
        tokens_in = _as_int_or_none(result.get("tokens_in"))
        tokens_out = _as_int_or_none(result.get("tokens_out"))
        tokens_thoughts = _as_int_or_none(result.get("tokens_thoughts"))
        tokens_total = _as_int_or_none(result.get("tokens_total"))
        trace_id = _text_or_none(result.get("trace_id"), max_len=128)
        observation_id = _text_or_none(result.get("observation_id"), max_len=128)
        message_id = _text_or_none(result.get("message_id"), max_len=128)
        request_id = _text_or_none(result.get("request_id"), max_len=128) or default_request_id
        retry_count = _as_int_or_none(result.get("retry_count"))
        routing_provider = _text_or_none(result.get("routing_provider"), max_len=64)
        routing_route_index = _as_int_or_none(result.get("routing_route_index"))
        routing_fallback_used = _as_bool_or_none(result.get("routing_fallback_used"))
    else:
        resp_text = result[0] if isinstance(result, tuple) else result
        model_name = _text_or_none(result[5], max_len=128) if isinstance(result, tuple) else None
        latency_seconds = float(result[7]) if isinstance(result, tuple) and result[7] is not None else None
        tokens_in = _as_int_or_none(result[8]) if isinstance(result, tuple) else None
        tokens_out = _as_int_or_none(result[9]) if isinstance(result, tuple) else None
        tokens_thoughts = _as_int_or_none(result[10]) if isinstance(result, tuple) else None
        tokens_total = _as_int_or_none(result[11]) if isinstance(result, tuple) else None
        trace_id = None
        observation_id = None
        message_id = None
        request_id = default_request_id
        retry_count = None
        routing_provider = None
        routing_route_index = None
        routing_fallback_used = None

    if not isinstance(resp_text, str) or not resp_text.strip():
        raise HTTPException(status_code=502, detail="LLM request failed")

    return (
        resp_text,
        model_name,
        latency_seconds,
        tokens_in,
        tokens_out,
        tokens_thoughts,
        tokens_total,
        trace_id,
        observation_id,
        message_id,
        request_id,
        retry_count,
        routing_provider,
        routing_route_index,
        routing_fallback_used,
    )


def _record_stage_metric(
    *,
    session: Session,
    attempt_id: UUID,
    user: User,
    stage: str,
    latency_ms: int | None,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    tokens_total: int | None = None,
    retry_count: int | None = None,
) -> None:
    session.add(
        AttemptStageMetric(
            id=uuid4(),
            attempt_id=attempt_id,
            user_id=user.id,
            anon_user_id=user.anon_user_id,
            stage=stage,
            latency_ms=latency_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            tokens_total=tokens_total,
            retry_count=retry_count,
            created_at=datetime.now(timezone.utc),
        )
    )


def _upsert_error_bank_entry(
    *,
    session: Session,
    user: User,
    error_type: str | None,
    concept_tag: str | None,
    verdict: str | None,
) -> None:
    normalized_concept_tag = _text_or_none(concept_tag, max_len=128) or ""
    normalized_error_type = (
        normalize_error_type(error_type, concept_tag=normalized_concept_tag)
        or _text_or_none(error_type, max_len=64)
    )
    if not normalized_error_type:
        return

    now = datetime.now(timezone.utc)
    entry = session.exec(
        select(ErrorBankEntry).where(
            ErrorBankEntry.anon_user_id == user.anon_user_id,
            ErrorBankEntry.error_type == normalized_error_type,
            ErrorBankEntry.concept_tag == normalized_concept_tag,
        )
    ).first()

    if entry:
        entry.count += 1
        entry.updated_at = now
        entry.last_seen_at = now
        if verdict == "unclear":
            entry.unclear_count += 1
        session.add(entry)
    else:
        session.add(
            ErrorBankEntry(
                id=uuid4(),
                anon_user_id=user.anon_user_id,
                error_type=normalized_error_type,
                concept_tag=normalized_concept_tag,
                count=1,
                fixed_count=0,
                unclear_count=1 if verdict == "unclear" else 0,
                created_at=now,
                updated_at=now,
                last_seen_at=now,
            )
        )


def _record_error_bank_resolution(
    *,
    session: Session,
    user: User,
    concept_tag: str | None,
) -> None:
    normalized_concept_tag = _text_or_none(concept_tag, max_len=128)
    if not normalized_concept_tag:
        return

    entries = session.exec(
        select(ErrorBankEntry).where(
            ErrorBankEntry.anon_user_id == user.anon_user_id,
            ErrorBankEntry.concept_tag == normalized_concept_tag,
            ErrorBankEntry.count > ErrorBankEntry.fixed_count,
        )
    ).all()
    if not entries:
        return

    now = datetime.now(timezone.utc)
    for entry in entries:
        entry.fixed_count += 1
        entry.updated_at = now
        session.add(entry)


def _record_structured_error_event(
    *,
    session: Session,
    attempt_id: UUID,
    user: User,
    mode: str,
    verdict: str | None,
    error_type: str | None,
    concept_tag: str | None,
    step_reference: str | None,
    error_step: str | None,
    correct_approach: str | None,
    error_confidence: float | None,
) -> None:
    if mode != "check_solution":
        return
    if verdict not in {"incorrect", "unclear"}:
        return

    normalized_concept_tag = _text_or_none(concept_tag, max_len=128)
    normalized_error_type = normalize_error_type(error_type, concept_tag=normalized_concept_tag)
    normalized_step_reference = _text_or_none(step_reference, max_len=128)
    normalized_error_step = _text_or_none(error_step, max_len=1000)
    normalized_correct_approach = _text_or_none(correct_approach, max_len=1000)

    if not any([normalized_error_type, normalized_error_step, normalized_correct_approach]):
        return

    session.add(
        ErrorEvent(
            id=uuid4(),
            attempt_id=attempt_id,
            user_id=user.id,
            topic=normalized_concept_tag,
            subtopic=normalized_step_reference,
            wrong_step=normalized_error_step,
            correct_step=normalized_correct_approach,
            error_type=normalized_error_type,
            confidence=error_confidence,
            created_at=datetime.now(timezone.utc),
        )
    )


def _record_error_event_from_deferred_payload(
    *,
    session: Session,
    attempt_id: UUID,
    user: User,
    payload: dict[str, object],
) -> str | None:
    raw_error_type = _text_or_none(payload.get("error_type"), max_len=64)
    normalized_error_type = normalize_error_type(raw_error_type) or raw_error_type
    topic = _text_or_none(payload.get("topic"), max_len=128)
    subtopic = _text_or_none(payload.get("subtopic"), max_len=128)
    wrong_step = _text_or_none(payload.get("wrong_step"), max_len=1000)
    correct_step = _text_or_none(payload.get("correct_step"), max_len=1000)
    confidence = _as_float_or_none(payload.get("confidence"))

    if not normalized_error_type:
        return None

    session.add(
        ErrorEvent(
            id=uuid4(),
            attempt_id=attempt_id,
            user_id=user.id,
            topic=topic,
            subtopic=subtopic,
            wrong_step=wrong_step,
            correct_step=correct_step,
            error_type=normalized_error_type,
            confidence=confidence,
            created_at=datetime.now(timezone.utc),
        )
    )
    return topic


def _as_bounded_float(value: object, *, minimum: float = 0.0, maximum: float = 1.0) -> float | None:
    number = _as_float_or_none(value)
    if number is None:
        return None
    if number < minimum:
        return minimum
    if number > maximum:
        return maximum
    return number


def _coerce_error_box(value: object, *, page_count: int) -> dict[str, float | int] | None:
    if not isinstance(value, dict):
        return None

    page = _as_int_or_none(value.get("page"))
    if page is None:
        page = 1
    page = max(1, min(page, page_count))

    x_min = _as_bounded_float(value.get("x_min"))
    y_min = _as_bounded_float(value.get("y_min"))
    x_max = _as_bounded_float(value.get("x_max"))
    y_max = _as_bounded_float(value.get("y_max"))
    if None in {x_min, y_min, x_max, y_max}:
        return None
    if x_min >= x_max or y_min >= y_max:
        return None

    return {
        "page": page,
        "x_min": x_min,
        "y_min": y_min,
        "x_max": x_max,
        "y_max": y_max,
    }


def _annotate_merged_solution_image(
    *,
    solution_pages_bytes: list[bytes],
    error_box: dict[str, float | int],
) -> bytes:
    solution_pages = [
        _bytes_to_pil_image(page_bytes, filename=f"solution_{index}.png")
        for index, page_bytes in enumerate(solution_pages_bytes, start=1)
    ]
    merged_image, placements = _merge_solution_pages_for_artifact_image(solution_pages)

    page_index = int(error_box["page"]) - 1
    if page_index < 0 or page_index >= len(placements):
        raise ValueError("error_box page is out of range")

    placement = placements[page_index]
    left = placement["x_offset"] + int(float(error_box["x_min"]) * placement["width"])
    top = placement["y_offset"] + int(float(error_box["y_min"]) * placement["height"])
    right = placement["x_offset"] + int(float(error_box["x_max"]) * placement["width"])
    bottom = placement["y_offset"] + int(float(error_box["y_max"]) * placement["height"])
    if right <= left or bottom <= top:
        raise ValueError("error_box produced an invalid rectangle")

    draw = ImageDraw.Draw(merged_image)
    stroke_width = max(3, min(merged_image.width, merged_image.height) // 200)
    draw.rectangle((left, top, right, bottom), outline="red", width=stroke_width)
    draw.text((left, max(0, top - 24)), "Error", fill="red")

    buffer = BytesIO()
    merged_image.save(buffer, format="PNG")
    return buffer.getvalue()


def _run_deferred_error_analysis(
    *,
    attempt_id: UUID,
    problem_id: UUID,
    user_id: UUID,
    anon_user_id: str,
    mode: str,
    prompt_variant: str,
    pipeline_mode: str,
    expert_mode: str,
    resolved_session_id: str | None,
    message_is: str,
    prob_bytes: bytes,
    prob_filename: str | None,
    solution_pages_bytes: list[bytes],
    solution_image_key: str,
) -> None:
    classification_prompt = _augment_prompt_for_pages(
        base_prompt=_augment_deferred_error_prompt(
            base_prompt=_load_deferred_error_prompt(),
            message_is=message_is,
        ),
        page_count=len(solution_pages_bytes),
    )

    prob_image = _bytes_to_pil_image(prob_bytes, filename=prob_filename or "problem.png")
    solution_images = [
        _bytes_to_pil_image(page_bytes, filename=f"solution_{index}.png")
        for index, page_bytes in enumerate(solution_pages_bytes, start=1)
    ]

    deferred_request_id = str(uuid4())
    environment = _text_or_none(os.getenv("ENVIRONMENT"), max_len=64)
    trace_metadata = {
        "feature": "notebook",
        "flow": "solve_problem",
        "phase": "deferred_error_analysis",
        "requestType": "deferred_error_analysis",
        "route": "POST /query (deferred error analysis)",
        "problemId": str(problem_id),
        "attemptId": str(attempt_id),
        "userId": str(user_id),
        "sessionId": resolved_session_id,
        "promptVariant": prompt_variant,
        "pipelineMode": pipeline_mode,
        "expertMode": expert_mode,
        "requestId": deferred_request_id,
        "promptVersion": "errors/v4/prompt.txt",
        "environment": environment,
    }

    payload: dict[str, object] | None = None
    for _attempt in range(2):
        try:
            deferred_result = call_deferred_error_with_retry(
                prompt=classification_prompt,
                prob_image=prob_image,
                sol_images=solution_images,
                mode=f"{mode}_deferred_error",
                max_retries=1,
                trace_name=f"{mode}-deferred-error",
                trace_metadata=trace_metadata,
                trace_user_id=str(user_id),
                trace_session_id=resolved_session_id,
                request_id=deferred_request_id,
            )
            deferred_resp_text, *_rest = _extract_llm_result(
                deferred_result,
                default_request_id=deferred_request_id,
            )
            parsed = json.loads(deferred_resp_text)
            if not isinstance(parsed, dict):
                raise ValueError("Deferred error payload must be an object")
            payload = parsed
            break
        except Exception:
            payload = None

    if payload is None:
        payload = {
            "topic": "",
            "subtopic": "",
            "wrong_step": "",
            "correct_step": message_is,
            "error_type": "uncategorized",
            "error_box": None,
            "confidence": 0.0,
        }

    error_box = _coerce_error_box(payload.get("error_box"), page_count=len(solution_pages_bytes))
    if error_box is not None:
        try:
            annotated_solution_bytes = _annotate_merged_solution_image(
                solution_pages_bytes=solution_pages_bytes,
                error_box=error_box,
            )
            upload_bytes(
                key=solution_image_key,
                data=annotated_solution_bytes,
                content_type="image/png",
            )
        except Exception:
            error_box = None
    payload["error_box"] = error_box

    with Session(engine) as session:
        user = session.get(User, user_id)
        if not user or not user.consent_analytics:
            return

        topic = _record_error_event_from_deferred_payload(
            session=session,
            attempt_id=attempt_id,
            user=user,
            payload=payload,
        )
        _upsert_error_bank_entry(
            session=session,
            user=user,
            error_type=_text_or_none(payload.get("error_type"), max_len=64),
            concept_tag=topic,
            verdict="incorrect",
        )
        _record_event(
            session=session,
            user_id=user.id,
            problem_id=problem_id,
            attempt_id=attempt_id,
            event_type="error_classified",
            mode=mode,
            verdict="incorrect",
            metadata_json=json.dumps(
                {
                    "prompt_version": "errors/v4/prompt.txt",
                    "error_box": error_box,
                    "solution_image_overwritten": error_box is not None,
                }
            ),
        )
        session.commit()


def _normalize_upload_lists(
    *,
    sol_images: list[UploadFile],
    drawing_data_pages: list[UploadFile],
) -> tuple[list[UploadFile], list[UploadFile]]:
    solution_uploads = [upload for upload in sol_images if upload is not None]
    drawing_uploads = [upload for upload in drawing_data_pages if upload is not None]

    if not solution_uploads or not drawing_uploads:
        raise HTTPException(
            status_code=422,
            detail="prob_image, sol_images, and drawing_data_pages are required",
        )
    if len(solution_uploads) != len(drawing_uploads):
        raise HTTPException(
            status_code=422,
            detail="sol_images and drawing_data_pages must have matching counts",
        )
    if len(solution_uploads) > QUERY_MAX_PAGE_COUNT:
        raise HTTPException(
            status_code=413,
            detail=f"Submission has too many pages. Maximum is {QUERY_MAX_PAGE_COUNT}.",
        )
    return solution_uploads, drawing_uploads


def _validate_upload_sizes(
    *,
    prob_bytes: bytes,
    solution_pages_bytes: list[bytes],
    drawing_pages_bytes: list[bytes],
) -> None:
    if len(prob_bytes) > QUERY_MAX_SINGLE_FILE_BYTES:
        raise HTTPException(
            status_code=413,
            detail="Submission is too large. Try a simpler or smaller problem image and submit again.",
        )

    total_size = len(prob_bytes)
    for page_bytes in solution_pages_bytes:
        if len(page_bytes) > QUERY_MAX_SINGLE_FILE_BYTES:
            raise HTTPException(
                status_code=413,
                detail="Submission is too large. Try simplifying your written work and submit again.",
            )
        total_size += len(page_bytes)

    for page_bytes in drawing_pages_bytes:
        if len(page_bytes) > QUERY_MAX_SINGLE_FILE_BYTES:
            raise HTTPException(
                status_code=413,
                detail="Submission is too large. Try reducing drawing complexity and submit again.",
            )
        total_size += len(page_bytes)

    if total_size > QUERY_MAX_TOTAL_BYTES:
        raise HTTPException(
            status_code=413,
            detail="Submission is too large. Try fewer or simpler pages and submit again.",
        )


def _normalize_page_count(_value: int | None, *, uploaded_pages: int) -> int:
    if uploaded_pages < 1:
        return 1
    return min(uploaded_pages, QUERY_MAX_PAGE_COUNT)


def _merge_solution_pages_for_artifact(solution_pages: list[Image.Image]) -> bytes:
    merged, _placements = _merge_solution_pages_for_artifact_image(solution_pages)
    buffer = BytesIO()
    merged.save(buffer, format="PNG")
    return buffer.getvalue()


def _merge_solution_pages_for_artifact_image(
    solution_pages: list[Image.Image],
) -> tuple[Image.Image, list[dict[str, int]]]:
    if not solution_pages:
        raise HTTPException(status_code=422, detail="At least one solution page is required")

    normalized_pages: list[Image.Image] = []
    for page in solution_pages:
        # Flatten transparency onto white so pencil/pen strokes stay visible.
        if "A" in page.getbands():
            rgba_page = page.convert("RGBA")
            white_background = Image.new("RGBA", rgba_page.size, (255, 255, 255, 255))
            normalized_pages.append(Image.alpha_composite(white_background, rgba_page).convert("RGB"))
        else:
            normalized_pages.append(page.convert("RGB"))
    horizontal_padding = 24
    vertical_padding = 24
    separator_height = 20
    max_width = max(page.width for page in normalized_pages)
    total_height = (
        vertical_padding * 2
        + sum(page.height for page in normalized_pages)
        + separator_height * max(0, len(normalized_pages) - 1)
    )

    merged = Image.new(
        "RGB",
        (max_width + (horizontal_padding * 2), total_height),
        color=(255, 255, 255),
    )

    y_offset = vertical_padding
    placements: list[dict[str, int]] = []
    for page in normalized_pages:
        x_offset = horizontal_padding + ((max_width - page.width) // 2)
        merged.paste(page, (x_offset, y_offset))
        placements.append(
            {
                "x_offset": x_offset,
                "y_offset": y_offset,
                "width": page.width,
                "height": page.height,
            }
        )
        y_offset += page.height + separator_height

    return merged, placements


@router.post("/query")
async def query(
    background_tasks: BackgroundTasks,
    request: Request,
    problem_id: UUID = Form(...),
    mode: Literal["hint", "check_solution", "reveal"] = Form(...),
    prob_image: UploadFile = File(...),
    sol_images: list[UploadFile] = File(...),
    drawing_data_pages: list[UploadFile] = File(...),
    page_count: int | None = Form(default=1),
    pipeline_mode: str | None = Form(default="two_pass"),
    expert_mode: str | None = Form(default="off"),
    confirmed_reading_json: str | None = Form(default=None),
    client_request_id: str | None = Form(default=None),
    session_id: str | None = Form(default=None),
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    request_started_perf = time.perf_counter()
    preprocess_started_perf = request_started_perf
    prompt_variant = _resolve_mode_prompt_variant()
    expert_prompt_variant = _resolve_expert_mode_prompt_variant()
    legibility_prompt_variant = _resolve_legibility_prompt_variant()
    pipeline_mode = _resolve_pipeline_mode(pipeline_mode)
    resolved_expert_mode = _normalize_expert_mode(expert_mode)
    mode_prompt_path = _resolve_mode_prompt_path(
        mode=mode,
        prompt_variant=prompt_variant,
        expert_prompt_variant=expert_prompt_variant,
        expert_mode=resolved_expert_mode,
    )

    base_prompt = _load_prompt(
        mode,
        prompt_variant=prompt_variant,
        expert_prompt_variant=expert_prompt_variant,
        expert_mode=resolved_expert_mode,
    )
    legibility_base_prompt = _load_legibility_prompt(prompt_variant=legibility_prompt_variant)
    attempt_id = uuid4()
    mode_prompt_version = _text_or_none(
        str(mode_prompt_path.relative_to(PROMPTS_BASE)).replace("\\", "/"),
        max_len=64,
    )
    legibility_prompt_version = _text_or_none(f"legibility/{legibility_prompt_variant}/prompt.txt", max_len=64)
    reasoning_request_id = str(uuid4())
    legibility_request_id = str(uuid4())

    solution_uploads, drawing_uploads = _normalize_upload_lists(
        sol_images=sol_images,
        drawing_data_pages=drawing_data_pages,
    )

    prob_bytes = await prob_image.read()
    solution_pages_bytes = [await upload.read() for upload in solution_uploads]
    drawing_pages_bytes = [await upload.read() for upload in drawing_uploads]

    if not prob_bytes or any(not page for page in solution_pages_bytes) or any(not page for page in drawing_pages_bytes):
        raise HTTPException(
            status_code=422,
            detail="prob_image, sol_images, and drawing_data_pages are required",
        )
    _validate_upload_sizes(
        prob_bytes=prob_bytes,
        solution_pages_bytes=solution_pages_bytes,
        drawing_pages_bytes=drawing_pages_bytes,
    )

    prob_pil = _to_pil_image(prob_image, prob_bytes)
    solution_pil_pages = [
        _to_pil_image(upload, page_bytes)
        for upload, page_bytes in zip(solution_uploads, solution_pages_bytes)
    ]
    preprocess_latency_ms = int((time.perf_counter() - preprocess_started_perf) * 1000)
    problem = session.exec(
        select(Problem).where(Problem.id == problem_id, Problem.user_id == user.id)
    ).first()
    if not problem:
        raise HTTPException(status_code=404, detail="Problem not found")

    header_client_request_id = request.headers.get("x-client-request-id")
    header_session_id = request.headers.get("x-session-id")
    resolved_client_request_id = _text_or_none(client_request_id or header_client_request_id, max_len=128)
    resolved_session_id = _text_or_none(session_id or header_session_id, max_len=128)
    resolved_page_count = _normalize_page_count(page_count, uploaded_pages=len(solution_uploads))
    confirmed_reading_entries = _parse_confirmed_reading_json(
        confirmed_reading_json,
        page_count=resolved_page_count,
    )
    reasoning_prompt = _augment_prompt_for_pages(base_prompt=base_prompt, page_count=resolved_page_count)
    reasoning_prompt = _augment_prompt_with_confirmed_reading(
        base_prompt=reasoning_prompt,
        confirmed_entries=confirmed_reading_entries,
    )
    legibility_prompt = _augment_prompt_for_pages(
        base_prompt=legibility_base_prompt,
        page_count=resolved_page_count,
    )
    environment = _text_or_none(os.getenv("ENVIRONMENT"), max_len=64)

    trace_metadata_base = {
        "feature": "notebook",
        "flow": "solve_problem",
        "problemId": str(problem.id),
        "attemptId": str(attempt_id),
        "userId": str(user.id),
        "clientRequestId": resolved_client_request_id,
        "sessionId": resolved_session_id,
        "pageCount": resolved_page_count,
        "promptVariant": prompt_variant,
        "pipelineMode": pipeline_mode,
        "expertMode": resolved_expert_mode,
        "confirmedReadingProvided": bool(confirmed_reading_entries),
        "environment": environment,
        "retryCount": None,
        "success": None,
    }
    legibility_trace_metadata = dict(trace_metadata_base)
    legibility_trace_metadata.update(
        {
            "phase": "legibility",
            "requestType": "legibility",
            "route": "POST /query (legibility)",
            "requestId": legibility_request_id,
            "promptVariant": legibility_prompt_variant,
            "promptVersion": legibility_prompt_version,
        }
    )
    reasoning_trace_metadata = dict(trace_metadata_base)
    reasoning_trace_metadata.update(
        {
            "phase": "reasoning",
            "requestType": mode,
            "route": "POST /query",
            "requestId": reasoning_request_id,
            "promptVersion": mode_prompt_version,
        }
    )

    payload: dict[str, object] | None = None
    selected_prompt_version: str | None = None
    model_name: str | None = None
    latency_seconds: float | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    tokens_thoughts: int | None = None
    tokens_total: int | None = None
    trace_id: str | None = None
    observation_id: str | None = None
    message_id: str | None = None
    request_id: str = reasoning_request_id
    retry_count: int | None = None
    routing_provider: str | None = None
    routing_route_index: int | None = None
    routing_fallback_used: bool | None = None
    legibility_stage_latency_ms: int | None = None
    legibility_stage_tokens_in: int | None = None
    legibility_stage_tokens_out: int | None = None
    legibility_stage_tokens_total: int | None = None
    legibility_stage_retry_count: int | None = None
    reasoning_stage_latency_ms: int | None = None
    reasoning_stage_tokens_in: int | None = None
    reasoning_stage_tokens_out: int | None = None
    reasoning_stage_tokens_total: int | None = None
    reasoning_stage_retry_count: int | None = None

    should_run_legibility = pipeline_mode == "two_pass" and not confirmed_reading_entries

    if should_run_legibility:
        legibility_prob_pil = _downscale_for_legibility(prob_pil)
        legibility_solution_pages = [_downscale_for_legibility(page) for page in solution_pil_pages]
        try:
            legibility_result = call_legibility_with_retry(
                prompt=legibility_prompt,
                prob_image=legibility_prob_pil,
                sol_images=legibility_solution_pages,
                mode=f"{mode}_legibility",
                trace_name=f"{mode}-legibility",
                trace_metadata=legibility_trace_metadata,
                trace_user_id=str(user.id),
                trace_session_id=resolved_session_id,
                request_id=legibility_request_id,
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Legibility check failed: {exc}") from exc

        try:
            (
                legibility_resp_text,
                legibility_model_name,
                legibility_latency_seconds,
                legibility_tokens_in,
                legibility_tokens_out,
                legibility_tokens_thoughts,
                legibility_tokens_total,
                legibility_trace_id,
                legibility_observation_id,
                legibility_message_id,
                legibility_request_id,
                legibility_retry_count,
                legibility_routing_provider,
                legibility_routing_route_index,
                legibility_routing_fallback_used,
            ) = _extract_llm_result(legibility_result, default_request_id=legibility_request_id)
            legibility_payload_raw = json.loads(legibility_resp_text)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=502, detail=f"Legibility model returned invalid JSON: {exc}") from exc

        if not isinstance(legibility_payload_raw, dict):
            raise HTTPException(status_code=502, detail="Legibility model returned invalid payload")

        (
            legibility_failed,
            _legibility_all_readable,
            legibility_regions,
        ) = _evaluate_legibility_payload(legibility_payload_raw, fail_closed=True)

        selected_prompt_version = legibility_prompt_version
        model_name = legibility_model_name
        latency_seconds = legibility_latency_seconds
        tokens_in = legibility_tokens_in
        tokens_out = legibility_tokens_out
        tokens_thoughts = legibility_tokens_thoughts
        tokens_total = legibility_tokens_total
        trace_id = legibility_trace_id
        observation_id = legibility_observation_id
        message_id = legibility_message_id
        request_id = legibility_request_id
        retry_count = legibility_retry_count
        routing_provider = legibility_routing_provider
        routing_route_index = legibility_routing_route_index
        routing_fallback_used = legibility_routing_fallback_used
        legibility_stage_latency_ms = (
            int(legibility_latency_seconds * 1000) if legibility_latency_seconds is not None else None
        )
        legibility_stage_tokens_in = legibility_tokens_in
        legibility_stage_tokens_out = legibility_tokens_out
        legibility_stage_tokens_total = legibility_tokens_total
        legibility_stage_retry_count = legibility_retry_count

        if legibility_failed:
            reading_confidence = _as_float_or_none(legibility_payload_raw.get("reading_confidence"))
            interpreted_reading = _build_ambiguous_step_entries(
                page_count=resolved_page_count,
                ambiguous_steps=legibility_regions,
            )
            if interpreted_reading and (
                reading_confidence is None or reading_confidence >= READING_CONFIRM_CONFIDENCE_MIN
            ):
                payload = _build_confirm_reading_payload(
                    ambiguous_steps=legibility_regions,
                    interpreted_reading=interpreted_reading,
                    reading_confidence=reading_confidence,
                )
            else:
                payload = _build_unclear_payload(
                    regions=legibility_regions,
                )
        legibility_prob_pil.close()
        for page in legibility_solution_pages:
            page.close()

    if payload is None:
        try:
            reasoning_result = call_mode_v3_with_retry(
                prompt=reasoning_prompt,
                prob_image=prob_pil,
                sol_images=solution_pil_pages,
                mode=mode,
                trace_name=mode,
                trace_metadata=reasoning_trace_metadata,
                trace_user_id=str(user.id),
                trace_session_id=resolved_session_id,
                request_id=reasoning_request_id,
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"LLM request failed: {exc}") from exc

        try:
            (
                reasoning_resp_text,
                reasoning_model_name,
                reasoning_latency_seconds,
                reasoning_tokens_in,
                reasoning_tokens_out,
                reasoning_tokens_thoughts,
                reasoning_tokens_total,
                reasoning_trace_id,
                reasoning_observation_id,
                reasoning_message_id,
                reasoning_request_id,
                reasoning_retry_count,
                reasoning_routing_provider,
                reasoning_routing_route_index,
                reasoning_routing_fallback_used,
            ) = _extract_llm_result(reasoning_result, default_request_id=reasoning_request_id)
            reasoning_payload_raw = json.loads(reasoning_resp_text)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=502, detail=f"Model returned invalid JSON: {exc}") from exc

        if not isinstance(reasoning_payload_raw, dict):
            raise HTTPException(status_code=502, detail="Model returned invalid payload")
        payload = dict(reasoning_payload_raw)

        selected_prompt_version = mode_prompt_version
        model_name = reasoning_model_name
        latency_seconds = reasoning_latency_seconds
        tokens_in = reasoning_tokens_in
        tokens_out = reasoning_tokens_out
        tokens_thoughts = reasoning_tokens_thoughts
        tokens_total = reasoning_tokens_total
        trace_id = reasoning_trace_id
        observation_id = reasoning_observation_id
        message_id = reasoning_message_id
        request_id = reasoning_request_id
        retry_count = reasoning_retry_count
        routing_provider = reasoning_routing_provider
        routing_route_index = reasoning_routing_route_index
        routing_fallback_used = reasoning_routing_fallback_used
        reasoning_stage_latency_ms = (
            int(reasoning_latency_seconds * 1000) if reasoning_latency_seconds is not None else None
        )
        reasoning_stage_tokens_in = reasoning_tokens_in
        reasoning_stage_tokens_out = reasoning_tokens_out
        reasoning_stage_tokens_total = reasoning_tokens_total
        reasoning_stage_retry_count = reasoning_retry_count

    if _text_or_none(payload.get("response_type"), max_len=64) == "confirm_reading":
        if user.consent_analytics:
            ambiguous_steps = payload.get("ambiguous_steps")
            interpreted_reading = payload.get("interpreted_reading")
            _record_event(
                session=session,
                user_id=user.id,
                problem_id=problem.id,
                attempt_id=None,
                event_type="reading_confirmation_requested",
                mode=mode,
                verdict="unclear",
                metadata_json=json.dumps(
                    {
                        "page_count": resolved_page_count,
                        "prompt_variant": prompt_variant,
                        "legibility_prompt_variant": legibility_prompt_variant,
                        "pipeline_mode": pipeline_mode,
                        "expert_mode": resolved_expert_mode,
                        "reading_confidence": _as_float_or_none(payload.get("reading_confidence")),
                        "ambiguous_region_count": (
                            len(ambiguous_steps) if isinstance(ambiguous_steps, list) else 0
                        ),
                        "interpreted_reading_count": (
                            len(interpreted_reading) if isinstance(interpreted_reading, list) else 0
                        ),
                        "trace_id": trace_id,
                        "observation_id": observation_id,
                        "request_id": request_id,
                        "routing_provider": routing_provider,
                        "routing_route_index": routing_route_index,
                        "routing_fallback_used": routing_fallback_used,
                        "client_request_id": resolved_client_request_id,
                        "session_id": resolved_session_id,
                    }
                ),
            )
            session.commit()

        response_payload = dict(payload)
        response_payload["expert_mode"] = resolved_expert_mode
        response_payload["observability"] = {
            "traceId": trace_id,
            "observationId": observation_id,
            "messageId": message_id,
            "requestId": request_id,
            "modelName": model_name,
            "promptVersion": selected_prompt_version,
            "retryCount": retry_count,
            "routingProvider": routing_provider,
            "routingRouteIndex": routing_route_index,
            "routingFallbackUsed": routing_fallback_used,
            "clientRequestId": resolved_client_request_id,
            "sessionId": resolved_session_id,
        }
        return JSONResponse(content=response_payload)

    latency_ms = int(latency_seconds * 1000) if latency_seconds is not None else None
    verdict = _text_or_none(payload.get("verdict"), max_len=64)
    response_type = _text_or_none(payload.get("response_type"), max_len=64)
    payload = {
        "verdict": verdict or "",
        "response_type": response_type or "",
        "message_is": _text_or_none(payload.get("message_is")) or "",
    }

    merged_solution_bytes = _merge_solution_pages_for_artifact(solution_pil_pages)
    base_key = f"users/{user.id}/problems/{problem.id}/attempts/{attempt_id}"
    problem_image_key = f"{base_key}/problem_image{_safe_suffix(prob_image, '.png')}"
    solution_image_key = f"{base_key}/solution_image.png"
    drawing_data_key = f"{base_key}/drawing_data_manifest.json"
    solution_page_artifacts = [
        (
            f"{base_key}/solution_pages/{page_index:03d}{_safe_suffix(upload, '.png')}",
            upload,
            page_bytes,
        )
        for page_index, (upload, page_bytes) in enumerate(zip(solution_uploads, solution_pages_bytes), start=1)
    ]
    drawing_page_artifacts = [
        (
            f"{base_key}/drawing_pages/{page_index:03d}{_safe_suffix(upload, '.bin')}",
            upload,
            page_bytes,
        )
        for page_index, (upload, page_bytes) in enumerate(zip(drawing_uploads, drawing_pages_bytes), start=1)
    ]
    page_manifest = {
        "version": 1,
        "page_count": resolved_page_count,
        "solution_page_count": len(solution_uploads),
        "drawing_page_count": len(drawing_uploads),
        "prompt_variant": prompt_variant,
        "pipeline_mode": pipeline_mode,
        "expert_mode": resolved_expert_mode,
        "solution_page_keys": [artifact[0] for artifact in solution_page_artifacts],
        "drawing_page_keys": [artifact[0] for artifact in drawing_page_artifacts],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    storage_started_perf = time.perf_counter()
    try:
        upload_bytes(
            key=problem_image_key,
            data=prob_bytes,
            content_type=prob_image.content_type or "application/octet-stream",
        )
        upload_bytes(
            key=solution_image_key,
            data=merged_solution_bytes,
            content_type="image/png",
        )
        upload_bytes(
            key=drawing_data_key,
            data=json.dumps(page_manifest).encode("utf-8"),
            content_type="application/json",
        )
        for solution_page_key, upload, page_bytes in solution_page_artifacts:
            upload_bytes(
                key=solution_page_key,
                data=page_bytes,
                content_type=upload.content_type or "application/octet-stream",
            )
        for drawing_page_key, upload, page_bytes in drawing_page_artifacts:
            upload_bytes(
                key=drawing_page_key,
                data=page_bytes,
                content_type=upload.content_type or "application/octet-stream",
            )
        storage_latency_ms = int((time.perf_counter() - storage_started_perf) * 1000)
    except R2ConfigurationError as exc:
        raise HTTPException(status_code=500, detail=f"R2 not configured: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to store artifacts in R2: {exc}") from exc

    attempt = Attempt(
        id=attempt_id,
        problem_id=problem.id,
        user_id=user.id,
        anon_user_id=user.anon_user_id,
        mode=mode,
        page_count=resolved_page_count,
        client_request_id=resolved_client_request_id,
        session_id=resolved_session_id,
        prompt_variant=prompt_variant,
        pipeline_mode=pipeline_mode,
        expert_mode=resolved_expert_mode,
        problem_image_key=problem_image_key,
        solution_image_key=solution_image_key,
        drawing_data_key=drawing_data_key,
        solution_page_keys=[artifact[0] for artifact in solution_page_artifacts],
        drawing_page_keys=[artifact[0] for artifact in drawing_page_artifacts],
        raw_response_json=payload,
        verdict=verdict,
        response_type=response_type,
        model_name=model_name,
        prompt_version=selected_prompt_version,
        latency_ms=latency_ms,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        tokens_thoughts=tokens_thoughts,
        tokens_total=tokens_total,
        trace_id=trace_id,
        observation_id=observation_id,
        request_id=request_id,
        message_is=_text_or_none(payload.get("message_is")),
        created_at=datetime.now(timezone.utc),
    )
    session.add(attempt)
    # Ensure the parent attempt row is inserted before analytics FK inserts.
    session.flush()
    total_latency_ms = int((time.perf_counter() - request_started_perf) * 1000)
    if user.consent_analytics:
        _record_stage_metric(
            session=session,
            attempt_id=attempt_id,
            user=user,
            stage="preprocess",
            latency_ms=preprocess_latency_ms,
        )
        if legibility_stage_latency_ms is not None:
            _record_stage_metric(
                session=session,
                attempt_id=attempt_id,
                user=user,
                stage="legibility",
                latency_ms=legibility_stage_latency_ms,
                tokens_in=legibility_stage_tokens_in,
                tokens_out=legibility_stage_tokens_out,
                tokens_total=legibility_stage_tokens_total,
                retry_count=legibility_stage_retry_count,
            )
        if reasoning_stage_latency_ms is not None:
            _record_stage_metric(
                session=session,
                attempt_id=attempt_id,
                user=user,
                stage="reasoning",
                latency_ms=reasoning_stage_latency_ms,
                tokens_in=reasoning_stage_tokens_in,
                tokens_out=reasoning_stage_tokens_out,
                tokens_total=reasoning_stage_tokens_total,
                retry_count=reasoning_stage_retry_count,
            )
        _record_stage_metric(
            session=session,
            attempt_id=attempt_id,
            user=user,
            stage="storage",
            latency_ms=storage_latency_ms,
        )
        _record_stage_metric(
            session=session,
            attempt_id=attempt_id,
            user=user,
            stage="total",
            latency_ms=total_latency_ms,
        )
        _record_event(
            session=session,
            user_id=user.id,
            problem_id=problem.id,
            attempt_id=attempt_id,
            event_type="attempt_submitted",
            mode=mode,
            verdict=attempt.verdict,
            metadata_json=json.dumps(
                {
                    "page_count": resolved_page_count,
                    "prompt_variant": prompt_variant,
                    "pipeline_mode": pipeline_mode,
                    "expert_mode": resolved_expert_mode,
                }
            ),
        )
        _record_event(
            session=session,
            user_id=user.id,
            problem_id=problem.id,
            attempt_id=attempt_id,
            event_type="attempt_failed" if attempt.verdict in {"incorrect", "unclear"} else "attempt_succeeded",
            mode=mode,
            verdict=attempt.verdict,
            metadata_json=json.dumps(
                {
                    "page_count": resolved_page_count,
                    "prompt_variant": prompt_variant,
                    "pipeline_mode": pipeline_mode,
                    "expert_mode": resolved_expert_mode,
                }
            ),
        )
    session.commit()

    if user.consent_analytics and verdict == "incorrect":
        background_tasks.add_task(
            _run_deferred_error_analysis,
            attempt_id=attempt_id,
            problem_id=problem.id,
            user_id=user.id,
            anon_user_id=user.anon_user_id,
            mode=mode,
            prompt_variant=prompt_variant,
            pipeline_mode=pipeline_mode,
            expert_mode=resolved_expert_mode,
            resolved_session_id=resolved_session_id,
            message_is=_text_or_none(payload.get("message_is")) or "",
            prob_bytes=prob_bytes,
            prob_filename=prob_image.filename,
            solution_pages_bytes=solution_pages_bytes,
            solution_image_key=solution_image_key,
        )

    response_payload = dict(payload)
    response_payload["expert_mode"] = resolved_expert_mode
    response_payload["observability"] = {
        "traceId": trace_id,
        "observationId": observation_id,
        "messageId": message_id,
        "requestId": request_id,
        "modelName": model_name,
        "promptVersion": selected_prompt_version,
        "retryCount": retry_count,
        "routingProvider": routing_provider,
        "routingRouteIndex": routing_route_index,
        "routingFallbackUsed": routing_fallback_used,
        "clientRequestId": resolved_client_request_id,
        "sessionId": resolved_session_id,
    }
    return JSONResponse(content=response_payload)
