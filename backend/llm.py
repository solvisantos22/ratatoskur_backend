from __future__ import annotations

import base64
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Sequence

from dotenv import load_dotenv
from google import genai
from google.genai.errors import ServerError
from pydantic import BaseModel, Field

try:
    from langfuse import Langfuse
except Exception:  # pragma: no cover - defensive import guard for platform/library mismatch
    Langfuse = None

load_dotenv(Path(__file__).resolve().parent / ".env")

logger = logging.getLogger(__name__)

# Gemini 3 Flash Preview paid-tier rates used elsewhere in this project docs.
INPUT_COST_PER_1M_TOKENS_USD = float(os.getenv("INPUT_COST_PER_1M_TOKENS_USD", "0.50"))
OUTPUT_COST_PER_1M_TOKENS_USD = float(os.getenv("OUTPUT_COST_PER_1M_TOKENS_USD", "3.00"))

# Alert if estimated per-call cost jumps above this delta compared to previous call.
COST_SPIKE_THRESHOLD_USD = float(os.getenv("COST_SPIKE_THRESHOLD_USD", "0.005"))

# In-memory baseline for simple spike detection (first call seeds baseline only).
previous_estimated_call_cost_usd: float | None = None

LLM_ROUTING_ENABLED = os.getenv("LLM_ROUTING_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
LLM_ROUTE_MAX_WORKERS = int(os.getenv("LLM_ROUTE_MAX_WORKERS", "8"))
LLM_MAX_RETRIES_PER_ROUTE = int(os.getenv("LLM_MAX_RETRIES_PER_ROUTE", "2"))
LLM_PROVIDER_HTTP_TIMEOUT_SECONDS = float(os.getenv("LLM_PROVIDER_HTTP_TIMEOUT_SECONDS", "60"))
LLM_OPENAI_MODEL = os.getenv("LLM_OPENAI_MODEL", "gpt-5-mini")
LLM_OPENAI_REASONING_EFFORT = os.getenv("LLM_OPENAI_REASONING_EFFORT", "low")
LLM_ANTHROPIC_MODEL = os.getenv("LLM_ANTHROPIC_MODEL", "claude-3-5-haiku-20241022")
LLM_ANTHROPIC_API_URL = os.getenv("LLM_ANTHROPIC_API_URL", "https://api.anthropic.com/v1/messages")
LLM_ANTHROPIC_VERSION = os.getenv("LLM_ANTHROPIC_VERSION", "2023-06-01")
LLM_ANTHROPIC_MAX_TOKENS = int(os.getenv("LLM_ANTHROPIC_MAX_TOKENS", "2048"))
LLM_REASONING_SOFT_TIMEOUT_SECONDS = float(os.getenv("LLM_REASONING_SOFT_TIMEOUT_SECONDS", "15"))
LLM_LEGIBILITY_SOFT_TIMEOUT_SECONDS = float(os.getenv("LLM_LEGIBILITY_SOFT_TIMEOUT_SECONDS", "8"))
LLM_DEFERRED_SOFT_TIMEOUT_SECONDS = os.getenv("LLM_DEFERRED_SOFT_TIMEOUT_SECONDS")
_route_executor: ThreadPoolExecutor | None = None


@dataclass(frozen=True)
class ModelRoute:
    provider: str
    model: str
    thinking_level: str | None
    soft_timeout_seconds: float | None


@dataclass(frozen=True)
class ProviderCallResult:
    response_text: str
    model_name: str
    tokens_in: int
    tokens_out: int
    tokens_thoughts: int
    tokens_total: int
    estimated_call_cost_usd: float | None


class ModelSoftTimeout(RuntimeError):
    pass


class ProviderUnavailable(RuntimeError):
    pass


class LLMResponse(BaseModel):
    verdict: str
    response_type: str
    message_is: str
    error_type: str
    error_step: str | None = None
    correct_approach: str | None = None
    error_confidence: float | None = None
    all_readable: bool
    ambiguous_regions: list["LegibilityRegion"] = Field(default_factory=list)
    missing_parts: list[str] = Field(default_factory=list)
    clarity_warning: bool | None = None
    missing_justification: bool | None = None
    concept_tag: str | None = None
    suggested_justification: str | None = None
    step_reference: str | None = None
    can_skip: bool | None = None


class ModeV3Response(BaseModel):
    verdict: str
    response_type: str
    message_is: str


class LegibilityRegion(BaseModel):
    page: int | None = None
    snippet: str | None = None
    reason: str | None = None


class LegibilityResponse(BaseModel):
    all_readable: bool
    reading_confidence: float | None = None
    ambiguous_steps: list[LegibilityRegion] = Field(default_factory=list)


class ExamAnswerExtractionResponse(BaseModel):
    answer_text: str | None = None


class DeferredErrorResponse(BaseModel):
    class ErrorBox(BaseModel):
        page: int | None = None
        x_min: float
        y_min: float
        x_max: float
        y_max: float

    topic: str | None = None
    subtopic: str | None = None
    wrong_step: str | None = None
    correct_step: str | None = None
    error_type: str
    error_box: ErrorBox | None = None
    confidence: float | None = None


def is_langfuse_enabled() -> bool:
    return langfuse is not None


def _build_langfuse_client() -> Langfuse | None:
    """Create a Langfuse client when credentials are available.

    Returns None if tracing is not configured or initialization fails.
    """
    if Langfuse is None:
        logger.warning("Langfuse disabled: import failed")
        return None

    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")

    if not public_key or not secret_key:
        logger.info("Langfuse disabled: LANGFUSE_PUBLIC_KEY/SECRET_KEY not set")
        return None

    # Support both host-style and base-url-style env naming.
    host = os.getenv("LANGFUSE_HOST") or os.getenv("LANGFUSE_BASE_URL")

    try:
        if host:
            return Langfuse(public_key=public_key, secret_key=secret_key, host=host)
        return Langfuse(public_key=public_key, secret_key=secret_key)
    except Exception:
        logger.exception("Langfuse initialization failed")
        return None


def _build_genai_client() -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")
    return genai.Client(api_key=api_key)


langfuse = _build_langfuse_client()
client = _build_genai_client()


def _trace_event(trace: Any, name: str, metadata: dict[str, Any]) -> None:
    if trace is None:
        return
    try:
        if hasattr(trace, "event"):
            trace.event(name=name, metadata=metadata)
        elif hasattr(trace, "create_event"):
            trace.create_event(name=name, metadata=metadata)
        elif hasattr(langfuse, "create_event"):
            langfuse.create_event(name=name, metadata=metadata)
        else:
            logger.warning("No compatible Langfuse event API found")
    except Exception:
        logger.exception("Failed to send Langfuse trace event")


def _extract_entity_id(entity: Any) -> str | None:
    if entity is None:
        return None
    for attr in ("id", "trace_id", "observation_id"):
        value = getattr(entity, attr, None)
        if value:
            return str(value)
    if isinstance(entity, dict):
        for key in ("id", "trace_id", "observation_id"):
            value = entity.get(key)
            if value:
                return str(value)
    return None


def _estimate_call_cost_usd(*, tokens_in: int, tokens_out: int, tokens_thoughts: int) -> float:
    safe_tokens_in = 0 if tokens_in is None else tokens_in
    safe_tokens_out = 0 if tokens_out is None else tokens_out
    safe_tokens_thoughts = 0 if tokens_thoughts is None else tokens_thoughts
    billed_output_tokens = max(0, safe_tokens_out) + max(0, safe_tokens_thoughts)
    return (max(0, safe_tokens_in) / 1_000_000.0) * INPUT_COST_PER_1M_TOKENS_USD + (
        billed_output_tokens / 1_000_000.0
    ) * OUTPUT_COST_PER_1M_TOKENS_USD


def _warn_if_cost_spike(current_cost_usd: float) -> None:
    global previous_estimated_call_cost_usd
    if previous_estimated_call_cost_usd is None:
        previous_estimated_call_cost_usd = current_cost_usd
        return

    increase = current_cost_usd - previous_estimated_call_cost_usd
    if increase > COST_SPIKE_THRESHOLD_USD:
        logger.warning(
            "COST SPIKE DETECTED\nPrevious cost: $%.6f\nCurrent cost: $%.6f\nIncrease: $%.6f",
            previous_estimated_call_cost_usd,
            current_cost_usd,
            increase,
        )
    previous_estimated_call_cost_usd = current_cost_usd


def _route_pool() -> ThreadPoolExecutor:
    global _route_executor
    if _route_executor is None:
        _route_executor = ThreadPoolExecutor(max_workers=max(1, LLM_ROUTE_MAX_WORKERS))
    return _route_executor


def _env_float_or_none(value: str | None) -> float | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    parsed = float(stripped)
    return parsed if parsed > 0 else None


def _soft_timeout_for_call(*, mode: str, response_schema: type[BaseModel]) -> float | None:
    if not LLM_ROUTING_ENABLED:
        return None
    if response_schema is LegibilityResponse or mode.endswith("_legibility"):
        return LLM_LEGIBILITY_SOFT_TIMEOUT_SECONDS
    if response_schema is DeferredErrorResponse or "deferred" in mode:
        return _env_float_or_none(LLM_DEFERRED_SOFT_TIMEOUT_SECONDS)
    return LLM_REASONING_SOFT_TIMEOUT_SECONDS


def _configured_route_chain(
    *,
    primary_model: str,
    primary_thinking_level: str | None,
    soft_timeout_seconds: float | None,
) -> list[ModelRoute]:
    primary = ModelRoute(
        provider="gemini",
        model=primary_model,
        thinking_level=primary_thinking_level,
        soft_timeout_seconds=soft_timeout_seconds,
    )
    if not LLM_ROUTING_ENABLED:
        return [primary]

    raw_chain = os.getenv("LLM_FALLBACK_CHAIN")
    if raw_chain:
        routes = [primary]
        for raw_item in raw_chain.split(","):
            parts = [part.strip() for part in raw_item.split(":")]
            if len(parts) < 2 or not parts[0] or not parts[1]:
                logger.warning("Ignoring invalid LLM_FALLBACK_CHAIN item: %s", raw_item)
                continue
            routes.append(
                ModelRoute(
                    provider=parts[0].lower(),
                    model=parts[1],
                    thinking_level=parts[2] if len(parts) >= 3 and parts[2] else None,
                    soft_timeout_seconds=soft_timeout_seconds,
                )
            )
        return _disable_timeout_without_fallback(_dedupe_routes(routes))

    routes = [primary]
    if (primary_thinking_level or "").lower() not in {"low", "minimal", "none"}:
        routes.append(
            ModelRoute(
                provider="gemini",
                model=primary_model,
                thinking_level="low",
                soft_timeout_seconds=soft_timeout_seconds,
            )
        )
    if os.getenv("OPENAI_API_KEY"):
        routes.append(
            ModelRoute(
                provider="openai",
                model=LLM_OPENAI_MODEL,
                thinking_level=LLM_OPENAI_REASONING_EFFORT,
                soft_timeout_seconds=soft_timeout_seconds,
            )
        )
    if os.getenv("ANTHROPIC_API_KEY"):
        routes.append(
            ModelRoute(
                provider="anthropic",
                model=LLM_ANTHROPIC_MODEL,
                thinking_level=None,
                soft_timeout_seconds=soft_timeout_seconds,
            )
        )
    return _disable_timeout_without_fallback(_dedupe_routes(routes))


def _dedupe_routes(routes: list[ModelRoute]) -> list[ModelRoute]:
    deduped: list[ModelRoute] = []
    seen: set[tuple[str, str, str | None]] = set()
    for route in routes:
        key = (route.provider, route.model, route.thinking_level)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(route)
    return deduped


def _disable_timeout_without_fallback(routes: list[ModelRoute]) -> list[ModelRoute]:
    if len(routes) != 1:
        return routes
    route = routes[0]
    if route.soft_timeout_seconds is None:
        return routes
    return [
        ModelRoute(
            provider=route.provider,
            model=route.model,
            thinking_level=route.thinking_level,
            soft_timeout_seconds=None,
        )
    ]


def _run_with_soft_timeout(fn, *, timeout_seconds: float | None) -> ProviderCallResult:
    if timeout_seconds is None:
        return fn()
    future = _route_pool().submit(fn)
    try:
        return future.result(timeout=timeout_seconds)
    except FutureTimeoutError as exc:
        future.cancel()
        raise ModelSoftTimeout(f"model route exceeded soft timeout after {timeout_seconds:.1f}s") from exc


def _pil_to_png_data_url(image: Any) -> str:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _pil_to_base64_png(image: Any) -> str:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _json_schema_for_provider(response_schema: type[BaseModel]) -> dict[str, Any]:
    schema = response_schema.model_json_schema()
    return _sanitize_json_schema(schema)


def _sanitize_json_schema(value: Any) -> Any:
    if isinstance(value, list):
        return [_sanitize_json_schema(item) for item in value]
    if not isinstance(value, dict):
        return value

    sanitized: dict[str, Any] = {}
    for key, item in value.items():
        if key in {"title", "default", "examples"}:
            continue
        sanitized[key] = _sanitize_json_schema(item)

    if sanitized.get("type") == "object" or "properties" in sanitized:
        sanitized.setdefault("additionalProperties", False)
    return sanitized


def _start_trace(
    *,
    prompt: str,
    mode: str,
    name: str,
    request_id: str | None,
    user_id: str | None,
    session_id: str | None,
    metadata: dict[str, Any] | None,
) -> tuple[Any, str | None]:
    if langfuse is None:
        return None, None
    trace_input = {"prompt": prompt, "mode": mode}
    base_kwargs: dict[str, Any] = {"name": name, "input": trace_input}
    if metadata:
        base_kwargs["metadata"] = metadata
    try:
        # Legacy clients with explicit trace objects.
        if hasattr(langfuse, "trace"):
            trace_kwargs = dict(base_kwargs)
            if user_id:
                trace_kwargs["user_id"] = user_id
            if session_id:
                trace_kwargs["session_id"] = session_id
            if request_id:
                trace_kwargs["id"] = request_id
            trace = langfuse.trace(**trace_kwargs)
            return trace, _extract_entity_id(trace) or request_id
        if hasattr(langfuse, "create_trace"):
            trace_kwargs = dict(base_kwargs)
            if user_id:
                trace_kwargs["user_id"] = user_id
            if session_id:
                trace_kwargs["session_id"] = session_id
            if request_id:
                trace_kwargs["id"] = request_id
            trace = langfuse.create_trace(**trace_kwargs)
            return trace, _extract_entity_id(trace) or request_id

        # Langfuse v3 OTEL-style clients: use spans and attach trace metadata explicitly.
        if hasattr(langfuse, "start_span"):
            trace_context = None
            if hasattr(langfuse, "create_trace_id"):
                if request_id:
                    trace_context = {"trace_id": langfuse.create_trace_id(seed=request_id)}
                else:
                    trace_context = {"trace_id": langfuse.create_trace_id()}
            trace = langfuse.start_span(trace_context=trace_context, **base_kwargs)
            if hasattr(trace, "update_trace"):
                trace.update_trace(
                    user_id=user_id,
                    session_id=session_id,
                    metadata=metadata,
                    input=trace_input,
                )
            resolved_trace_id = (
                getattr(trace, "trace_id", None)
                or _extract_entity_id(trace)
                or (trace_context or {}).get("trace_id")
                or request_id
            )
            return trace, resolved_trace_id
        logger.warning("No compatible Langfuse trace/span API found")
        return None, None
    except Exception:
        logger.exception("Failed to start Langfuse trace/span")
        return None, None


def _trace_generation(
    trace: Any,
    *,
    model: str,
    prompt: str,
    output: str,
    mode: str,
    latency: float,
    tokens_in: int,
    tokens_out: int,
    tokens_total: int,
    tokens_thoughts: int,
) -> str | None:
    if trace is None:
        return None

    try:
        if hasattr(trace, "generation"):
            generation = trace.generation(
                name="gemini-generation",
                model=model,
                input=prompt,
                output=output,
                usage={
                    "prompt_tokens": tokens_in,
                    "completion_tokens": tokens_out,
                    "total_tokens": tokens_total,
                },
                metadata={
                    "mode": mode,
                    "latency": latency,
                    "thought_tokens": tokens_thoughts,
                },
            )
            return _extract_entity_id(generation)

        if hasattr(trace, "start_generation"):
            generation = trace.start_generation(
                name="gemini-generation",
                model=model,
                input=prompt,
                output=output,
                usage_details={
                    "input": tokens_in,
                    "output": tokens_out,
                    "total": tokens_total,
                },
                metadata={
                    "mode": mode,
                    "latency": latency,
                    "thought_tokens": tokens_thoughts,
                },
            )
            if hasattr(generation, "end"):
                generation.end()
            return _extract_entity_id(generation)

        logger.warning("No compatible Langfuse generation API found")
    except Exception:
        logger.exception("Failed to send Langfuse generation")
    return None


def _end_trace(trace: Any, *, output: Any = None, metadata: dict[str, Any] | None = None) -> None:
    if trace is None:
        return
    try:
        # Langfuse v3 span API: update trace attrs first, then end span.
        if hasattr(trace, "update_trace") and hasattr(trace, "end"):
            trace.update_trace(output=output, metadata=metadata)
            trace.end()
            return
        if hasattr(trace, "end"):
            kwargs: dict[str, Any] = {}
            if output is not None:
                kwargs["output"] = output
            if metadata:
                kwargs["metadata"] = metadata
            trace.end(**kwargs)
            return
        if hasattr(trace, "update"):
            kwargs = {}
            if output is not None:
                kwargs["output"] = output
            if metadata:
                kwargs["metadata"] = metadata
            trace.update(**kwargs)
    except Exception:
        logger.exception("Failed to finalize Langfuse trace")


def submit_langfuse_score(
    *,
    name: str,
    value: float,
    observation_id: str | None = None,
    trace_id: str | None = None,
    comment: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> tuple[bool, str | None]:
    if langfuse is None:
        return False, "Langfuse client not initialized"
    if not observation_id and not trace_id:
        return False, "Missing trace_id and observation_id"

    base_kwargs: dict[str, Any] = {
        "name": name,
        "value": value,
    }
    if comment:
        base_kwargs["comment"] = comment
    if metadata:
        base_kwargs["metadata"] = metadata

    target_kwargs: list[dict[str, str]] = []
    if trace_id and observation_id:
        target_kwargs.append({"trace_id": trace_id, "observation_id": observation_id})
        target_kwargs.append({"traceId": trace_id, "observationId": observation_id})
    if observation_id:
        target_kwargs.append({"observation_id": observation_id})
        target_kwargs.append({"observationId": observation_id})
    if trace_id:
        target_kwargs.append({"trace_id": trace_id})
        target_kwargs.append({"traceId": trace_id})

    score_methods = []
    if hasattr(langfuse, "score"):
        score_methods.append(langfuse.score)
    if hasattr(langfuse, "create_score"):
        score_methods.append(langfuse.create_score)

    last_error: str | None = None
    for method in score_methods:
        for target in target_kwargs:
            try:
                method(**base_kwargs, **target)
                if hasattr(langfuse, "flush"):
                    langfuse.flush()
                return True, None
            except TypeError:
                continue
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                logger.warning("Langfuse score submission attempt failed: %s", last_error)
                continue

    if last_error:
        logger.error("Langfuse score submission failed after all attempts: %s", last_error)
        return False, last_error
    return False, "No compatible Langfuse score method/parameters found"


def _build_multipage_contents(*, prompt: str, prob_image: Any, sol_images: Sequence[Any]) -> list[Any]:
    sol_images_list = list(sol_images)
    if not sol_images_list:
        raise ValueError("At least one solution image is required")

    contents: list[Any] = [prompt, "Problem image:", prob_image]
    total_solution_pages = len(sol_images_list)
    for page_index, page_image in enumerate(sol_images_list, start=1):
        contents.append(f"Student solution page {page_index} of {total_solution_pages} (ordered).")
        contents.append(page_image)
    return contents


def _call_gemini_route_once(
    *,
    route: ModelRoute,
    contents: list[Any],
    response_schema: type[BaseModel],
) -> ProviderCallResult:
    config: dict[str, Any] = {
        "response_mime_type": "application/json",
        "response_json_schema": response_schema.model_json_schema(),
    }
    if route.thinking_level:
        config["thinking_config"] = {"thinking_level": route.thinking_level}

    resp = client.models.generate_content(
        model=route.model,
        contents=contents,
        config=config,
    )

    usage = getattr(resp, "usage_metadata", None)
    tokens_in = getattr(usage, "prompt_token_count", 0)
    tokens_out = getattr(usage, "candidates_token_count", 0)
    tokens_total = getattr(usage, "total_token_count", 0)
    tokens_thoughts = getattr(usage, "thoughts_token_count", 0)
    estimated_call_cost_usd = _estimate_call_cost_usd(
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        tokens_thoughts=tokens_thoughts,
    )
    _warn_if_cost_spike(estimated_call_cost_usd)
    return ProviderCallResult(
        response_text=resp.text,
        model_name=route.model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        tokens_thoughts=tokens_thoughts,
        tokens_total=tokens_total,
        estimated_call_cost_usd=estimated_call_cost_usd,
    )


def _call_openai_route_once(
    *,
    route: ModelRoute,
    prompt: str,
    prob_image: Any,
    sol_images: Sequence[Any],
    response_schema: type[BaseModel],
) -> ProviderCallResult:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ProviderUnavailable("OPENAI_API_KEY is not set")

    import httpx

    content: list[dict[str, Any]] = [
        {"type": "input_text", "text": prompt},
        {"type": "input_text", "text": "Problem image:"},
        {"type": "input_image", "image_url": _pil_to_png_data_url(prob_image), "detail": "auto"},
    ]
    sol_images_list = list(sol_images)
    for page_index, page_image in enumerate(sol_images_list, start=1):
        content.append(
            {
                "type": "input_text",
                "text": f"Student solution page {page_index} of {len(sol_images_list)} (ordered).",
            }
        )
        content.append({"type": "input_image", "image_url": _pil_to_png_data_url(page_image), "detail": "auto"})

    body: dict[str, Any] = {
        "model": route.model,
        "input": [{"role": "user", "content": content}],
        "text": {
            "format": {
                "type": "json_schema",
                "name": response_schema.__name__,
                "schema": _json_schema_for_provider(response_schema),
                "strict": True,
            }
        },
    }
    if route.thinking_level:
        body["reasoning"] = {"effort": route.thinking_level}

    with httpx.Client(timeout=LLM_PROVIDER_HTTP_TIMEOUT_SECONDS) as http_client:
        response = http_client.post(
            "https://api.openai.com/v1/responses",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=body,
        )
        response.raise_for_status()
        payload = response.json()

    response_text = _extract_openai_response_text(payload)
    usage = payload.get("usage") or {}
    output_details = usage.get("output_tokens_details") or {}
    tokens_in = int(usage.get("input_tokens") or 0)
    tokens_out = int(usage.get("output_tokens") or 0)
    tokens_thoughts = int(output_details.get("reasoning_tokens") or 0)
    tokens_total = int(usage.get("total_tokens") or (tokens_in + tokens_out))
    return ProviderCallResult(
        response_text=response_text,
        model_name=f"openai:{payload.get('model') or route.model}",
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        tokens_thoughts=tokens_thoughts,
        tokens_total=tokens_total,
        estimated_call_cost_usd=None,
    )


def _extract_openai_response_text(payload: dict[str, Any]) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct

    chunks: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if not isinstance(content, dict):
                continue
            text = content.get("text")
            if isinstance(text, str):
                chunks.append(text)
    text = "".join(chunks).strip()
    if not text:
        raise RuntimeError("OpenAI response did not include output text")
    return text


def _call_anthropic_route_once(
    *,
    route: ModelRoute,
    prompt: str,
    prob_image: Any,
    sol_images: Sequence[Any],
    response_schema: type[BaseModel],
) -> ProviderCallResult:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ProviderUnavailable("ANTHROPIC_API_KEY is not set")

    import httpx

    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    content.append(
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": _pil_to_base64_png(prob_image),
            },
        }
    )
    sol_images_list = list(sol_images)
    for page_index, page_image in enumerate(sol_images_list, start=1):
        content.append(
            {
                "type": "text",
                "text": f"Student solution page {page_index} of {len(sol_images_list)} (ordered).",
            }
        )
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": _pil_to_base64_png(page_image),
                },
            }
        )

    body = {
        "model": route.model,
        "max_tokens": LLM_ANTHROPIC_MAX_TOKENS,
        "messages": [{"role": "user", "content": content}],
        "tools": [
            {
                "name": "emit_json",
                "description": "Return the response as structured JSON matching the required schema.",
                "input_schema": _json_schema_for_provider(response_schema),
            }
        ],
        "tool_choice": {"type": "tool", "name": "emit_json"},
    }

    with httpx.Client(timeout=LLM_PROVIDER_HTTP_TIMEOUT_SECONDS) as http_client:
        response = http_client.post(
            LLM_ANTHROPIC_API_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": LLM_ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
            json=body,
        )
        response.raise_for_status()
        payload = response.json()

    response_text = _extract_anthropic_response_text(payload)
    usage = payload.get("usage") or {}
    tokens_in = int(usage.get("input_tokens") or 0)
    tokens_out = int(usage.get("output_tokens") or 0)
    return ProviderCallResult(
        response_text=response_text,
        model_name=f"anthropic:{payload.get('model') or route.model}",
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        tokens_thoughts=0,
        tokens_total=tokens_in + tokens_out,
        estimated_call_cost_usd=None,
    )


def _extract_anthropic_response_text(payload: dict[str, Any]) -> str:
    text_chunks: list[str] = []
    for content in payload.get("content") or []:
        if not isinstance(content, dict):
            continue
        if content.get("type") == "tool_use" and isinstance(content.get("input"), dict):
            return json.dumps(content["input"], ensure_ascii=False)
        if content.get("type") == "text" and isinstance(content.get("text"), str):
            text_chunks.append(content["text"])
    text = "".join(text_chunks).strip()
    if not text:
        raise RuntimeError("Anthropic response did not include JSON text or tool input")
    return text


def _call_provider_route_once(
    *,
    route: ModelRoute,
    contents: list[Any],
    prompt: str,
    prob_image: Any,
    sol_images: Sequence[Any],
    response_schema: type[BaseModel],
) -> ProviderCallResult:
    if route.provider == "gemini":
        return _call_gemini_route_once(route=route, contents=contents, response_schema=response_schema)
    if route.provider == "openai":
        return _call_openai_route_once(
            route=route,
            prompt=prompt,
            prob_image=prob_image,
            sol_images=sol_images,
            response_schema=response_schema,
        )
    if route.provider == "anthropic":
        return _call_anthropic_route_once(
            route=route,
            prompt=prompt,
            prob_image=prob_image,
            sol_images=sol_images,
            response_schema=response_schema,
        )
    raise ProviderUnavailable(f"Unsupported provider: {route.provider}")


def _call_model_with_retry_internal(
    *,
    prompt: str,
    prob_image: Any,
    sol_images: Sequence[Any],
    mode: str,
    response_schema: type[BaseModel],
    model_name: str = "gemini-3-flash-preview",
    thinking_level: str | None = "medium",
    max_retries: int = 5,
    regenerate: bool = False,
    trace_name: str = "gemini-call",
    trace_metadata: dict[str, Any] | None = None,
    trace_user_id: str | None = None,
    trace_session_id: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    if max_retries < 1:
        raise ValueError("max_retries must be >= 1")

    sol_images_list = list(sol_images)
    contents = _build_multipage_contents(prompt=prompt, prob_image=prob_image, sol_images=sol_images_list)
    soft_timeout_seconds = _soft_timeout_for_call(mode=mode, response_schema=response_schema)
    routes = _configured_route_chain(
        primary_model=model_name,
        primary_thinking_level=thinking_level,
        soft_timeout_seconds=soft_timeout_seconds,
    )
    retries_per_route = max_retries
    if LLM_ROUTING_ENABLED and soft_timeout_seconds is not None:
        retries_per_route = max(1, min(max_retries, LLM_MAX_RETRIES_PER_ROUTE))

    t0 = time.time()
    trace, trace_id = _start_trace(
        prompt=prompt,
        mode=mode,
        name=trace_name,
        request_id=request_id,
        user_id=trace_user_id,
        session_id=trace_session_id,
        metadata=trace_metadata,
    )

    route_errors: list[str] = []
    total_attempt_count = 0

    for route_index, route in enumerate(routes):
        fallback_used = route_index > 0
        _trace_event(
            trace,
            name="model_route_started",
            metadata={
                "routeIndex": route_index,
                "provider": route.provider,
                "model": route.model,
                "thinkingLevel": route.thinking_level,
                "softTimeoutSeconds": route.soft_timeout_seconds,
                "fallbackUsed": fallback_used,
            },
        )

        for attempt in range(retries_per_route):
            total_attempt_count += 1
            route_started = time.time()
            try:
                result = _run_with_soft_timeout(
                    lambda route=route: _call_provider_route_once(
                        route=route,
                        contents=contents,
                        prompt=prompt,
                        prob_image=prob_image,
                        sol_images=sol_images_list,
                        response_schema=response_schema,
                    ),
                    timeout_seconds=route.soft_timeout_seconds,
                )

                latency = time.time() - t0
                route_latency = time.time() - route_started
                observation_id = _trace_generation(
                    trace,
                    model=result.model_name,
                    prompt=prompt,
                    output=result.response_text,
                    mode=mode,
                    latency=latency,
                    tokens_in=result.tokens_in,
                    tokens_out=result.tokens_out,
                    tokens_total=result.tokens_total,
                    tokens_thoughts=result.tokens_thoughts,
                )
                end_metadata = dict(trace_metadata or {})
                end_metadata.update(
                    {
                        "success": True,
                        "retryCount": total_attempt_count - 1,
                        "routeIndex": route_index,
                        "provider": route.provider,
                        "model": route.model,
                        "thinkingLevel": route.thinking_level,
                        "fallbackUsed": fallback_used,
                        "routeLatencySeconds": route_latency,
                    }
                )
                _end_trace(trace, output=result.response_text, metadata=end_metadata)
                if langfuse is not None and hasattr(langfuse, "flush"):
                    langfuse.flush()

                return {
                    "response_text": result.response_text,
                    "prompt": prompt,
                    "mode": mode,
                    "model_name": result.model_name,
                    "timestamp": datetime.now(),
                    "latency_seconds": latency,
                    "tokens_in": result.tokens_in,
                    "tokens_out": result.tokens_out,
                    "tokens_thoughts": result.tokens_thoughts,
                    "tokens_total": result.tokens_total,
                    "estimated_call_cost_usd": result.estimated_call_cost_usd,
                    "retry_count": total_attempt_count - 1,
                    "trace_id": trace_id,
                    "observation_id": observation_id,
                    "message_id": None,
                    "request_id": request_id,
                    "routing_provider": route.provider,
                    "routing_route_index": route_index,
                    "routing_fallback_used": fallback_used,
                }

            except ModelSoftTimeout as exc:
                error_text = str(exc)
                route_errors.append(f"{route.provider}:{route.model}:soft_timeout:{error_text}")
                _trace_event(
                    trace,
                    name="model_route_soft_timeout",
                    metadata={
                        "routeIndex": route_index,
                        "provider": route.provider,
                        "model": route.model,
                        "attempt": attempt + 1,
                        "error": error_text,
                    },
                )
                logger.warning(
                    "Model route timed out: provider=%s model=%s attempt=%s timeout=%s",
                    route.provider,
                    route.model,
                    attempt + 1,
                    route.soft_timeout_seconds,
                )
                break

            except ServerError as exc:
                error_text = str(exc)
                route_errors.append(f"{route.provider}:{route.model}:server_error:{error_text}")
                _trace_event(
                    trace,
                    name="model_route_server_error",
                    metadata={
                        "routeIndex": route_index,
                        "provider": route.provider,
                        "model": route.model,
                        "attempt": attempt + 1,
                        "maxRetries": retries_per_route,
                        "error": error_text,
                    },
                )
                if attempt < retries_per_route - 1:
                    wait_seconds = 2**attempt
                    logger.warning(
                        "Provider server error on route %s/%s attempt %s/%s. Retrying in %ss",
                        route.provider,
                        route.model,
                        attempt + 1,
                        retries_per_route,
                        wait_seconds,
                    )
                    time.sleep(wait_seconds)
                    continue
                break

            except ProviderUnavailable as exc:
                error_text = str(exc)
                route_errors.append(f"{route.provider}:{route.model}:unavailable:{error_text}")
                _trace_event(
                    trace,
                    name="model_route_unavailable",
                    metadata={
                        "routeIndex": route_index,
                        "provider": route.provider,
                        "model": route.model,
                        "error": error_text,
                    },
                )
                break

            except Exception as exc:
                error_text = f"{type(exc).__name__}: {exc}"
                route_errors.append(f"{route.provider}:{route.model}:error:{error_text}")
                _trace_event(
                    trace,
                    name="model_route_error",
                    metadata={
                        "routeIndex": route_index,
                        "provider": route.provider,
                        "model": route.model,
                        "attempt": attempt + 1,
                        "error": error_text,
                    },
                )
                logger.exception(
                    "Model route failed: provider=%s model=%s attempt=%s",
                    route.provider,
                    route.model,
                    attempt + 1,
                )
                break

    final_error = " | ".join(route_errors) or "No model routes were attempted"
    end_metadata = dict(trace_metadata or {})
    end_metadata.update(
        {
            "success": False,
            "retryCount": total_attempt_count,
            "routingErrors": route_errors,
            "routeCount": len(routes),
        }
    )
    _end_trace(trace, output={"error": final_error}, metadata=end_metadata)
    if langfuse is not None and hasattr(langfuse, "flush"):
        langfuse.flush()
    raise RuntimeError(f"All model routes failed: {final_error}")


def call_legibility_with_retry(
    prompt: str,
    prob_image: Any,
    sol_images: Sequence[Any],
    mode: str,
    max_retries: int = 5,
    regenerate: bool = False,
    trace_name: str = "gemini-legibility",
    trace_metadata: dict[str, Any] | None = None,
    trace_user_id: str | None = None,
    trace_session_id: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    return _call_model_with_retry_internal(
        prompt=prompt,
        prob_image=prob_image,
        sol_images=sol_images,
        mode=mode,
        response_schema=LegibilityResponse,
        model_name="gemini-3-flash-preview",
        thinking_level="low",
        max_retries=max_retries,
        regenerate=regenerate,
        trace_name=trace_name,
        trace_metadata=trace_metadata,
        trace_user_id=trace_user_id,
        trace_session_id=trace_session_id,
        request_id=request_id,
    )


def call_mode_v3_with_retry(
    prompt: str,
    prob_image: Any,
    sol_images: Sequence[Any],
    mode: str,
    max_retries: int = 5,
    regenerate: bool = False,
    trace_name: str = "gemini-mode-v3",
    trace_metadata: dict[str, Any] | None = None,
    trace_user_id: str | None = None,
    trace_session_id: str | None = None,
    request_id: str | None = None,
):
    return _call_model_with_retry_internal(
        prompt=prompt,
        prob_image=prob_image,
        sol_images=sol_images,
        mode=mode,
        response_schema=ModeV3Response,
        model_name="gemini-3-flash-preview",
        thinking_level="medium",
        max_retries=max_retries,
        regenerate=regenerate,
        trace_name=trace_name,
        trace_metadata=trace_metadata,
        trace_user_id=trace_user_id,
        trace_session_id=trace_session_id,
        request_id=request_id,
    )


def call_deferred_error_with_retry(
    prompt: str,
    prob_image: Any,
    sol_images: Sequence[Any],
    mode: str,
    max_retries: int = 5,
    regenerate: bool = False,
    trace_name: str = "gemini-deferred-error",
    trace_metadata: dict[str, Any] | None = None,
    trace_user_id: str | None = None,
    trace_session_id: str | None = None,
    request_id: str | None = None,
):
    return _call_model_with_retry_internal(
        prompt=prompt,
        prob_image=prob_image,
        sol_images=sol_images,
        mode=mode,
        response_schema=DeferredErrorResponse,
        model_name="gemini-3-flash-preview",
        thinking_level="high",
        max_retries=max_retries,
        regenerate=regenerate,
        trace_name=trace_name,
        trace_metadata=trace_metadata,
        trace_user_id=trace_user_id,
        trace_session_id=trace_session_id,
        request_id=request_id,
    )


def call_exam_answer_extraction_with_retry(
    *,
    prompt: str,
    answer_image: Any,
    request_id: str | None = None,
) -> dict[str, Any]:
    t0 = time.time()
    response = client.models.generate_content(
        model="models/gemini-3-flash-preview",
        contents=[prompt, answer_image],
        config={
            "response_mime_type": "application/json",
            "response_json_schema": ExamAnswerExtractionResponse.model_json_schema(),
            "thinking_config": {"thinking_level": "low"},
        },
    )
    latency = time.time() - t0
    return {
        "response_text": response.text,
        "prompt": prompt,
        "mode": "exam_answer_extraction",
        "model_name": "gemini:models/gemini-3-flash-preview",
        "timestamp": datetime.now(),
        "latency_seconds": latency,
        "request_id": request_id,
        "routing_provider": "gemini",
        "routing_route_index": 0,
        "routing_fallback_used": False,
    }


def call_model_with_retry(
    prompt: str,
    prob_image: Any,
    sol_images: Sequence[Any],
    mode: str,
    max_retries: int = 5,
    regenerate: bool = False,
    trace_name: str = "gemini-call",
    trace_metadata: dict[str, Any] | None = None,
    trace_user_id: str | None = None,
    trace_session_id: str | None = None,
    request_id: str | None = None,
):
    """Call Gemini with retries and optional Langfuse tracing."""
    return _call_model_with_retry_internal(
        prompt=prompt,
        prob_image=prob_image,
        sol_images=sol_images,
        mode=mode,
        response_schema=LLMResponse,
        model_name="gemini-3-flash-preview",
        thinking_level="medium",
        max_retries=max_retries,
        regenerate=regenerate,
        trace_name=trace_name,
        trace_metadata=trace_metadata,
        trace_user_id=trace_user_id,
        trace_session_id=trace_session_id,
        request_id=request_id,
    )
