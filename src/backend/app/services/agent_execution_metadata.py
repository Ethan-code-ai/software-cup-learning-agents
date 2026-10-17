import os
import re
from typing import Any

from app.schemas import AgentExecutionMetadata


_IDENTIFIER_PATTERN = re.compile(r"[^A-Za-z0-9._:/-]+")
_SOURCE_REF_PATTERN = re.compile(r"[^A-Za-z0-9._:/#-]+")
_BEARER_PATTERN = re.compile(r"(?i)bearer\s+[^\s;,]+")
_NAMED_SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?key|authorization|password|token|secret)\s*[:=]\s*[^\s;,]+"
)


def build_execution_metadata(result: object | None = None, **overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {}
    if result is not None:
        provider_metadata = getattr(result, "provider_metadata", None)
        if isinstance(provider_metadata, dict):
            values.update(
                {
                    "provider_duration_ms": provider_metadata.get("provider_duration_ms"),
                    "retry_count": provider_metadata.get("retry_count"),
                    "token_usage": provider_metadata.get("usage"),
                    "retrieved_count": provider_metadata.get("retrieved_count"),
                    "selected_evidence_count": provider_metadata.get("selected_evidence_count"),
                    "context_chars": provider_metadata.get("context_chars"),
                    "evidence_ids_used": provider_metadata.get("evidence_ids_used"),
                }
            )
        for field in (
            "execution_mode",
            "provider",
            "model",
            "fallback_used",
            "fallback_reason",
            "source_refs",
            "duration_ms",
            "provider_duration_ms",
            "retry_count",
            "token_usage",
            "retrieved_count",
            "selected_evidence_count",
            "context_chars",
            "evidence_ids_used",
        ):
            if hasattr(result, field):
                values[field] = getattr(result, field)
    for field in (
        "execution_mode",
        "provider",
        "model",
        "fallback_used",
        "fallback_reason",
        "source_refs",
        "duration_ms",
        "provider_duration_ms",
        "retry_count",
        "token_usage",
        "retrieved_count",
        "selected_evidence_count",
        "context_chars",
        "evidence_ids_used",
    ):
        if field in overrides:
            values[field] = overrides[field]
    return sanitize_execution_metadata(values).model_dump()


def sanitize_execution_metadata(value: dict[str, Any] | AgentExecutionMetadata | None) -> AgentExecutionMetadata:
    if isinstance(value, AgentExecutionMetadata):
        raw = value.model_dump()
    else:
        raw = value or {}

    fallback_used = bool(raw.get("fallback_used"))
    execution_mode = _execution_mode(raw.get("execution_mode"), fallback_used)
    if execution_mode == "rule_based_fallback":
        fallback_used = True
    provider = _safe_identifier(raw.get("provider"), "rule_based", 80)
    model = _safe_identifier(raw.get("model"), "", 160)
    fallback_reason = _safe_fallback_reason(raw.get("fallback_reason"))
    source_refs = _safe_source_refs(raw.get("source_refs"))
    duration_ms = _safe_duration(raw.get("duration_ms"))
    provider_duration_ms = _safe_duration(raw.get("provider_duration_ms"))
    retry_count = _safe_duration(raw.get("retry_count"))
    token_usage = _safe_token_usage(raw.get("token_usage"))
    return AgentExecutionMetadata(
        execution_mode=execution_mode,
        provider=provider,
        model=model,
        fallback_used=fallback_used,
        fallback_reason=fallback_reason,
        source_refs=source_refs,
        duration_ms=duration_ms,
        provider_duration_ms=provider_duration_ms,
        retry_count=retry_count,
        token_usage=token_usage,
        retrieved_count=_safe_duration(raw.get("retrieved_count")),
        selected_evidence_count=_safe_duration(raw.get("selected_evidence_count")),
        context_chars=_safe_duration(raw.get("context_chars")),
        evidence_ids_used=[item for item in (_safe_identifier(value, "", 8) for value in (raw.get("evidence_ids_used") or [])) if item][:3],
    )


def sanitize_trace_text(value: Any, max_length: int = 2000) -> str:
    """Redact known credentials and bound trace text without storing prompts or context."""
    if value is None:
        return ""
    text = str(value).replace("\r", " ").replace("\n", " ")
    for name, secret in os.environ.items():
        if any(marker in name.upper() for marker in ("KEY", "TOKEN", "SECRET", "PASSWORD")):
            if secret and len(secret) >= 4:
                text = text.replace(secret, "[REDACTED]")
    text = _BEARER_PATTERN.sub("Bearer [REDACTED]", text)
    text = _NAMED_SECRET_PATTERN.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)
    return " ".join(text.split())[:max_length]


def _execution_mode(value: Any, fallback_used: bool) -> str:
    normalized = str(value or "rule_based").strip().lower()
    if fallback_used or "fallback" in normalized:
        return "rule_based_fallback"
    if normalized == "llm":
        return "llm"
    return "rule_based"


def _safe_identifier(value: Any, default: str, max_length: int) -> str:
    text = str(value or default).strip()
    sanitized = _IDENTIFIER_PATTERN.sub("_", text).strip("_")
    return (sanitized or default)[:max_length]


def _safe_fallback_reason(value: Any) -> str | None:
    if value is None:
        return None
    normalized = sanitize_trace_text(value, 500)
    return normalized or None


def _safe_source_refs(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    refs: list[str] = []
    for item in value:
        candidate = item.get("source_ref") if isinstance(item, dict) else item
        if candidate is None:
            continue
        redacted = sanitize_trace_text(candidate, 180)
        normalized = _SOURCE_REF_PATTERN.sub("_", redacted).strip("_")
        if normalized and normalized not in refs:
            refs.append(normalized)
        if len(refs) >= 20:
            break
    return refs


def _safe_duration(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _safe_token_usage(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    safe: dict[str, int] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        try:
            amount = max(0, int(value.get(key, 0)))
        except (TypeError, ValueError):
            amount = 0
        if amount:
            safe[key] = amount
    return safe
