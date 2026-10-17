import json
import re
import time
from dataclasses import dataclass, field, replace
from typing import Annotated, Any, Literal, Protocol

from pydantic import AliasChoices, BaseModel, Field, ValidationError, field_validator

from app.adapters.llm_provider import LLMProviderError, LLMSettings, build_llm_provider
from app.adapters.protocols import LLMProvider
from app.core.enums import ProfileType
from app.schemas import StudentProfileCreate, StudentProfileDialogueCreate
from app.services.profile_builder import build_profile_from_dialogue, normalize_profile_dimensions
from app.services.content_safety_service import ContentSafetyService


class ProfileDimensions(BaseModel):
    profile_type: ProfileType = Field(validation_alias=AliasChoices("profile_type", "ProfileType"))
    learning_goal: str = Field(min_length=1, max_length=300)
    foundation_level: Literal["beginner", "intermediate", "advanced"]
    learning_preference: Literal[
        "step_by_step",
        "worked_examples",
        "code_driven",
        "visual_map",
        "summary_first",
    ]
    available_time: str = Field(min_length=1, max_length=120)
    weak_points: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(default_factory=list, max_length=5)
    resource_preference: Literal["讲解文档", "练习题", "思维导图", "拓展阅读", "代码实操案例"]

    @field_validator("resource_preference", mode="before")
    @classmethod
    def normalize_resource_preference(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "guided_note": "讲解文档",
            "guided_notes": "讲解文档",
            "practice_question": "练习题",
            "practice_questions": "练习题",
            "mind_map": "思维导图",
            "extended_reading": "拓展阅读",
            "coding_case": "代码实操案例",
            "coding_cases": "代码实操案例",
            "coding_exercise": "代码实操案例",
            "coding_exercises": "代码实操案例",
        }
        return aliases.get(normalized, value.strip())


PROFILE_BUILD_SCHEMA: dict[str, Any] = ProfileDimensions.model_json_schema()


@dataclass(frozen=True)
class ProfileBuildResult:
    profile: StudentProfileCreate
    execution_mode: str
    provider: str
    model: str
    fallback_used: bool
    fallback_reason: str | None
    evidence_summary: str
    duration_ms: int
    provider_metadata: dict[str, Any] = field(default_factory=dict)


class ProfileBuilderAgent(Protocol):
    def build(self, payload: StudentProfileDialogueCreate) -> ProfileBuildResult:
        raise NotImplementedError


class RuleBasedProfileBuilderAgent:
    def build(self, payload: StudentProfileDialogueCreate) -> ProfileBuildResult:
        started = time.perf_counter()
        profile = build_profile_from_dialogue(payload)
        return ProfileBuildResult(
            profile=profile,
            execution_mode="rule_based",
            provider="rule_based",
            model="",
            fallback_used=False,
            fallback_reason=None,
            evidence_summary=_rule_based_evidence_summary(profile),
            duration_ms=_elapsed_ms(started),
        )


class LLMProfileBuilderAgent:
    def __init__(
        self,
        provider: LLMProvider,
        fallback_agent: ProfileBuilderAgent | None = None,
        fallback_mode: str = "rule_based",
        provider_name: str = "openai_compatible",
        model: str = "",
    ) -> None:
        self.provider = provider
        self.fallback_agent = fallback_agent or RuleBasedProfileBuilderAgent()
        self.fallback_mode = fallback_mode if fallback_mode in {"rule_based", "error"} else "rule_based"
        self.provider_name = provider_name
        self.model = model

    def build(self, payload: StudentProfileDialogueCreate) -> ProfileBuildResult:
        started = time.perf_counter()
        try:
            safety = ContentSafetyService().review_input(payload.dialogue)
            if not safety.allowed:
                raise ValueError(f"Content safety blocked input: {safety.category}")
            result = self.provider.generate(
                _build_profile_messages(payload),
                response_schema=PROFILE_BUILD_SCHEMA,
            )
            dimensions = _parse_profile_dimensions(result.content)
            profile = _profile_from_dimensions(payload, dimensions)
            return ProfileBuildResult(
                profile=profile,
                execution_mode="llm",
                provider=str(result.metadata.get("provider") or self.provider_name),
                model=str(result.metadata.get("model") or self.model),
                fallback_used=False,
                fallback_reason=None,
                evidence_summary=_dimension_evidence_summary(dimensions),
                duration_ms=_elapsed_ms(started),
                provider_metadata=result.metadata,
            )
        except Exception as exc:
            reason = _fallback_reason(exc)
            if self.fallback_mode == "error":
                raise LLMProviderError(reason) from exc
            fallback = self.fallback_agent.build(payload)
            return replace(
                fallback,
                execution_mode="rule_based_fallback",
                provider=self.provider_name,
                model=self.model,
                fallback_used=True,
                fallback_reason=reason,
                duration_ms=_elapsed_ms(started),
                provider_metadata=getattr(exc, "metadata", {}),
            )


def build_profile_builder_agent(settings: LLMSettings | None = None) -> ProfileBuilderAgent:
    resolved = settings or LLMSettings.from_env()
    provider = build_llm_provider(resolved, purpose="profile_builder")
    if provider is None:
        return RuleBasedProfileBuilderAgent()
    return LLMProfileBuilderAgent(
        provider,
        fallback_mode=resolved.fallback_mode,
        provider_name=resolved.provider,
        model=resolved.model,
    )


def _build_profile_messages(payload: StudentProfileDialogueCreate) -> list[dict[str, str]]:
    explicit_context = {
        "user_id_present": payload.user_id is not None,
        "explicit_profile_type": str(payload.profile_type) if payload.profile_type else None,
    }
    return [
        {
            "role": "system",
            "content": (
                "你是学生初始画像构建 Agent。只依据学生对话抽取画像，不得编造经历。"
                "正确理解否定表达、隐含偏好和多个学习目标。只返回 JSON object，不输出 Markdown。"
            ),
        },
        {
            "role": "user",
            "content": (
                "请根据对话生成六维学生画像，输出必须符合以下 JSON schema：\n"
                f"{json.dumps(PROFILE_BUILD_SCHEMA, ensure_ascii=False)}\n\n"
                "约束：weak_points 最多 5 项；"
                "没有明确证据时使用保守值，不要把否定句中的关键词当作真实偏好。\n"
                f"允许使用的显式上下文：{json.dumps(explicit_context, ensure_ascii=False)}\n"
                f"学生对话：{payload.dialogue.strip()}"
            ),
        },
    ]


def _parse_profile_dimensions(content: str) -> ProfileDimensions:
    raw = _extract_json_object(content)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("LLM response contained invalid JSON.") from exc
    if not isinstance(parsed, dict):
        raise ValueError("LLM profile response must be a JSON object.")
    return ProfileDimensions.model_validate(parsed)


def _profile_from_dimensions(
    payload: StudentProfileDialogueCreate,
    dimensions: ProfileDimensions,
) -> StudentProfileCreate:
    preferences = {
        "style": dimensions.learning_preference,
        "resource": dimensions.resource_preference,
        "profile_origin": "user_dialogue",
        "learning_goal": dimensions.learning_goal,
        "foundation_level": dimensions.foundation_level,
        "learning_preference": dimensions.learning_preference,
        "available_time": dimensions.available_time,
        "weak_points": "、".join(_clean_weak_points(dimensions.weak_points)) or "待通过测验进一步定位",
        "resource_preference": dimensions.resource_preference,
    }
    return normalize_profile_dimensions(
        StudentProfileCreate(
            user_id=payload.user_id,
            profile_type=payload.profile_type or dimensions.profile_type,
            goal=dimensions.learning_goal,
            level=dimensions.foundation_level,
            preferences=preferences,
            time_budget=dimensions.available_time,
        )
    )


def _clean_weak_points(values: list[str]) -> list[str]:
    cleaned: list[str] = []
    for value in values:
        item = value.strip()[:80]
        if item and item not in cleaned:
            cleaned.append(item)
    return cleaned[:5]


def _extract_json_object(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end > start:
        return stripped[start : end + 1]
    raise ValueError("LLM response did not contain a JSON object.")


def _fallback_reason(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        fields = sorted(
            {
                f"{'.'.join(str(part) for part in error['loc'])}:{error['type']}"
                for error in exc.errors()
            }
        )
        detail = ",".join(fields[:4])
        return f"ValidationError: response schema validation failed ({detail})"
    if isinstance(exc, LLMProviderError):
        return str(exc)[:240]
    if isinstance(exc, ValueError):
        return f"ValueError: {str(exc)[:200]}"
    return f"{type(exc).__name__}: profile builder request failed"


def _rule_based_evidence_summary(profile: StudentProfileCreate) -> str:
    dimensions = profile.preferences
    return (
        f"规则抽取基础水平={profile.level}，学习偏好={dimensions.get('learning_preference')}，"
        f"资源偏好={dimensions.get('resource_preference')}。"
    )


def _dimension_evidence_summary(dimensions: ProfileDimensions) -> str:
    weak_points = "、".join(_clean_weak_points(dimensions.weak_points)) or "待测验定位"
    return (
        f"结构化抽取基础水平={dimensions.foundation_level}，学习偏好={dimensions.learning_preference}，"
        f"可用时间={dimensions.available_time}，薄弱点={weak_points}，"
        f"资源偏好={dimensions.resource_preference}。"
    )[:300]


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))
