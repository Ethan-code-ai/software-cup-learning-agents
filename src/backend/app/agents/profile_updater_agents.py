import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from app.adapters.protocols import LLMProvider
from app.services.content_safety_service import ContentSafetyService


PROFILE_TRACE_ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "weak_points",
        "resource_preference",
        "learning_preference",
        "foundation_level",
        "reason",
    ],
    "properties": {
        "weak_points": {"type": "array", "items": {"type": "string"}},
        "resource_preference": {"type": ["string", "null"]},
        "learning_preference": {"type": ["string", "null"]},
        "foundation_level": {"type": ["string", "null"], "enum": ["beginner", "intermediate", "advanced", None]},
        "reason": {"type": "string"},
    },
}


@dataclass(frozen=True)
class ProfileTraceAnalysis:
    weak_points: list[str]
    resource_preference: str | None
    learning_preference: str | None
    foundation_level: str | None
    reason: str
    provider: str = "openai_compatible"
    model: str = ""
    duration_ms: int = 0
    provider_metadata: dict[str, Any] = field(default_factory=dict)


class LLMBackedProfileUpdaterAgent:
    def __init__(self, provider: LLMProvider, provider_name: str = "openai_compatible", model: str = "") -> None:
        self.provider = provider
        self.provider_name = provider_name
        self.model = model

    def analyze(self, trace_steps: list[dict[str, str | int]]) -> ProfileTraceAnalysis:
        started = time.perf_counter()
        safety = ContentSafetyService().review_input(json.dumps(trace_steps, ensure_ascii=False, default=str))
        if not safety.allowed:
            raise ValueError(f"Content safety blocked input: {safety.category}")
        result = self.provider.generate(
            _build_profile_update_messages(trace_steps),
            response_schema=PROFILE_TRACE_ANALYSIS_SCHEMA,
        )
        parsed = _parse_profile_trace_analysis(result.content)
        return ProfileTraceAnalysis(
            weak_points=parsed.weak_points,
            resource_preference=parsed.resource_preference,
            learning_preference=parsed.learning_preference,
            foundation_level=parsed.foundation_level,
            reason=parsed.reason,
            provider=str(result.metadata.get("provider") or self.provider_name),
            model=str(result.metadata.get("model") or self.model),
            duration_ms=max(0, round((time.perf_counter() - started) * 1000)),
            provider_metadata=result.metadata,
        )


def _build_profile_update_messages(trace_steps: list[dict[str, str | int]]) -> list[dict[str, str]]:
    payload = json.dumps(trace_steps, ensure_ascii=False)
    return [
        {
            "role": "system",
            "content": (
                "你是学生画像更新 Agent。请只分析给定 Agent trace，不要编造未出现的学习行为。"
                "你必须只返回一个 JSON object，不要输出 Markdown。"
            ),
        },
        {
            "role": "user",
            "content": (
                "根据以下 Agent trace 更新学生画像，输出字段必须符合这个 JSON schema：\n"
                f"{json.dumps(PROFILE_TRACE_ANALYSIS_SCHEMA, ensure_ascii=False)}\n\n"
                "字段约束：\n"
                "- weak_points 使用中文知识点名称，最多 5 个。\n"
                "- resource_preference 可选值示例：讲解文档、练习题、思维导图、拓展阅读、代码实操案例。\n"
                "- learning_preference 可选值示例：step_by_step、worked_examples、code_driven、visual_map。\n"
                "- foundation_level 只能是 beginner、intermediate、advanced 或 null。\n"
                "- reason 用一句中文说明证据来源。\n\n"
                f"Agent trace:\n{payload}"
            ),
        },
    ]


def _parse_profile_trace_analysis(content: str) -> ProfileTraceAnalysis:
    raw = _extract_json_object(content)
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("Profile trace analysis must be a JSON object.")

    weak_points_raw = parsed.get("weak_points", [])
    if not isinstance(weak_points_raw, list):
        raise ValueError("weak_points must be a list.")
    weak_points = [str(item).strip() for item in weak_points_raw if str(item).strip()][:5]

    foundation_level = _optional_string(parsed.get("foundation_level"))
    if foundation_level not in {None, "beginner", "intermediate", "advanced"}:
        raise ValueError("foundation_level is out of schema.")

    reason = _optional_string(parsed.get("reason")) or "LLM 已基于 Agent trace 更新画像。"
    return ProfileTraceAnalysis(
        weak_points=weak_points,
        resource_preference=_optional_string(parsed.get("resource_preference")),
        learning_preference=_optional_string(parsed.get("learning_preference")),
        foundation_level=foundation_level,
        reason=reason,
    )


def _extract_json_object(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and end > start:
        return stripped[start : end + 1]
    raise ValueError("LLM response did not contain a JSON object.")


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
