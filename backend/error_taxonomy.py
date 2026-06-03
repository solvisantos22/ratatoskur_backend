from __future__ import annotations

import re
from collections.abc import Iterable


CANONICAL_ERROR_TO_TOPIC: dict[str, str] = {
    "sign_error": "algebra",
    "order_of_operations": "algebra",
    "distribution_error": "algebra",
    "equation_isolation_error": "algebra",
    "fraction_common_denominator_error": "fractions",
    "fraction_simplification_error": "fractions",
    "fraction_arithmetic_error": "fractions",
}

DEFAULT_ERROR_TARGETS_BY_TOPIC: dict[str, list[str]] = {
    "algebra": [
        "sign_error",
        "order_of_operations",
        "distribution_error",
        "equation_isolation_error",
    ],
    "fractions": [
        "fraction_common_denominator_error",
        "fraction_simplification_error",
        "fraction_arithmetic_error",
    ],
}

CANONICAL_ERROR_TYPES: set[str] = set(CANONICAL_ERROR_TO_TOPIC)

_ALIAS_MAP: dict[str, str] = {
    "conceptual": "equation_isolation_error",
    "conceptual_error": "equation_isolation_error",
    "concept_error": "equation_isolation_error",
    "logic": "equation_isolation_error",
    "logic_error": "equation_isolation_error",
    "reasoning_error": "equation_isolation_error",
    "calculation": "sign_error",
    "calculation_error": "sign_error",
    "arithmetic_error": "sign_error",
    "computational_error": "sign_error",
    "distribution": "distribution_error",
    "distributive_error": "distribution_error",
    "isolation_error": "equation_isolation_error",
    "solve_for_x_error": "equation_isolation_error",
    "fraction_addition_error": "fraction_common_denominator_error",
    "fraction_denominator_error": "fraction_common_denominator_error",
    "fraction_reduce_error": "fraction_simplification_error",
}

_CONCEPT_INFERENCE_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("common_denominator", "samnefn", "least_common_denominator", "lcd"), "fraction_common_denominator_error"),
    (("simplif", "reduce_fraction", "cancellation", "cancel", "stytt"), "fraction_simplification_error"),
    (("fraction", "brot", "numerator", "denominator"), "fraction_arithmetic_error"),
    (("distribution", "distributive", "dreifi"), "distribution_error"),
    (("order_of_operations", "pemdas", "operation_order"), "order_of_operations"),
    (("sign", "negative", "plus_minus", "formerki"), "sign_error"),
    (
        ("equation", "isolation", "equivalent_transformation", "factoring", "linear_equation", "solve_for"),
        "equation_isolation_error",
    ),
)


def normalize_error_type(error_type: str | None, *, concept_tag: str | None = None) -> str | None:
    normalized = _normalize_token(error_type)
    if not normalized:
        return None
    if normalized in CANONICAL_ERROR_TYPES:
        return normalized

    concept_inferred = infer_error_type_from_concept(concept_tag)
    if concept_inferred and normalized in {"conceptual", "conceptual_error", "logic", "logic_error", "calculation"}:
        return concept_inferred

    mapped = _ALIAS_MAP.get(normalized)
    if mapped:
        return mapped

    if concept_inferred:
        return concept_inferred
    return None


def infer_error_type_from_concept(concept_tag: str | None) -> str | None:
    concept = _normalize_token(concept_tag)
    if not concept:
        return None
    for fragments, error_type in _CONCEPT_INFERENCE_RULES:
        if any(fragment in concept for fragment in fragments):
            return error_type
    return None


def topic_for_error_type(error_type: str | None, *, concept_tag: str | None = None) -> str | None:
    canonical = normalize_error_type(error_type, concept_tag=concept_tag)
    if not canonical:
        return None
    return CANONICAL_ERROR_TO_TOPIC.get(canonical)


def normalize_error_type_list(values: Iterable[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        canonical = normalize_error_type(value)
        if not canonical or canonical in seen:
            continue
        deduped.append(canonical)
        seen.add(canonical)
    return deduped


def _normalize_token(value: str | None) -> str:
    if value is None:
        return ""
    token = value.strip().lower()
    if not token:
        return ""
    token = token.replace("-", "_").replace(" ", "_")
    token = re.sub(r"[^a-z0-9_]", "", token)
    token = re.sub(r"_+", "_", token).strip("_")
    return token
