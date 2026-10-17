import json
import time
from typing import Any, Protocol

from app.adapters.llm_provider import LLMProviderError
from app.adapters.protocols import LLMProvider
from app.agents.rule_based_agents import ResourceAgentResult, RuleBasedResourceAgent
from app.schemas import KnowledgeSearchResult
from app.services.content_safety_service import ContentSafetyService


class ResourceAgent(Protocol):
    def generate(
        self,
        concept_name: str,
        objective: str,
        resource_type: str,
        chunks: list[KnowledgeSearchResult],
        profile_preferences: dict[str, Any] | None = None,
    ) -> ResourceAgentResult:
        raise NotImplementedError


class LLMBackedResourceAgent:
    def __init__(
        self,
        provider: LLMProvider,
        fallback_agent: RuleBasedResourceAgent | None = None,
        fallback_mode: str = "rule_based",
        provider_name: str = "openai_compatible",
        model: str = "",
    ) -> None:
        self.provider = provider
        self.fallback_agent = fallback_agent or RuleBasedResourceAgent()
        self.fallback_mode = fallback_mode if fallback_mode in {"rule_based", "error"} else "rule_based"
        self.provider_name = provider_name
        self.model = model

    def generate(
        self,
        concept_name: str,
        objective: str,
        resource_type: str,
        chunks: list[KnowledgeSearchResult],
        profile_preferences: dict[str, Any] | None = None,
    ) -> ResourceAgentResult:
        started = time.perf_counter()
        source_refs = self.fallback_agent._source_refs(chunks)
        try:
            safety = ContentSafetyService().review_input(
                " ".join(
                    [
                        concept_name,
                        objective,
                        resource_type,
                        json.dumps(profile_preferences or {}, ensure_ascii=False, default=str),
                    ]
                )
            )
            if not safety.allowed:
                raise ValueError(f"Content safety blocked input: {safety.category}")
            if not chunks:
                raise ValueError("No retrieved course chunks are available.")
            result = self.provider.generate(
                _build_resource_messages(concept_name, objective, resource_type, chunks, profile_preferences or {}),
            )
            provider = str(result.metadata.get("provider") or self.provider_name)
            model = str(result.metadata.get("model") or self.model)
            return ResourceAgentResult(
                content=result.content,
                source_refs=source_refs,
                input_summary=f"使用真实 LLM 为知识点 {concept_name} 生成 {resource_type} 资源。",
                output_summary="LLM provider 返回个性化学习资源，包含资料引用和防幻觉提示。",
                decision_basis="通过 LLMProvider adapter 调用 OpenAI-compatible provider，并要求仅基于 KnowledgeBaseService 返回的 chunk 生成资源。",
                execution_mode="llm",
                provider=provider,
                model=model,
                duration_ms=_elapsed_ms(started),
                provider_metadata=result.metadata,
            )
        except Exception as exc:
            reason = _fallback_reason(exc)
            if self.fallback_mode == "error":
                raise LLMProviderError(reason) from exc
            fallback = self.fallback_agent.generate(concept_name, objective, resource_type, chunks, profile_preferences)
            return ResourceAgentResult(
                content=fallback.content,
                source_refs=fallback.source_refs,
                input_summary=fallback.input_summary,
                output_summary="LLM provider 不可用，已回退到 rule-based resource generation。",
                decision_basis=f"{fallback.decision_basis} Fallback reason: {reason}.",
                execution_mode="rule_based_fallback",
                provider=self.provider_name,
                model=self.model,
                fallback_used=True,
                fallback_reason=reason,
                duration_ms=_elapsed_ms(started),
                provider_metadata=getattr(exc, "metadata", {}),
            )


def _build_resource_messages(
    concept_name: str,
    objective: str,
    resource_type: str,
    chunks: list[KnowledgeSearchResult],
    profile_preferences: dict[str, Any],
) -> list[dict[str, str]]:
    context = "\n".join(
        f"[{index}] source={chunk.source_ref or chunk.chunk_id or 'unknown'} content={chunk.content}"
        for index, chunk in enumerate(chunks, start=1)
    )
    format_contract = _resource_format_contract(resource_type)
    return [
        {
            "role": "system",
            "content": (
                "Only cite source refs listed in the retrieved chunks. "
                "Use citations after key claims, for example [document:4#chunk:3]. "
                "Do not invent source refs. "
                "Keep the complete response within 900 Chinese characters; prefer compact sections and avoid repetition. "
                "你是数据结构课程的 Resource Agent。请用中文生成个性化学习资源。"
                "只能使用给定课程资料作为事实依据；资料不足时必须明确说明缺少什么，不要编造。"
                "必须严格体现资源类型差异，不要把所有资源都写成普通讲义。"
                "输出必须包含引用来源，并用 [1]、[2] 标注依据。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"知识点：{concept_name}\n"
                f"学习目标：{objective}\n"
                f"资源类型：{resource_type}\n"
                f"学生画像偏好：{profile_preferences}\n"
                f"资源格式要求：\n{format_contract}\n"
                f"课程资料：\n{context}"
            ),
        },
    ]


def _resource_format_contract(resource_type: str) -> str:
    contracts = {
        "guided_note": (
            "输出一份讲解文档。必须包含：\n"
            "1. 标题\n2. 核心概念解释\n3. 易错点\n4. 一个小例子\n5. 下一步学习建议。"
        ),
        "practice_questions": (
            "输出练习题，不要输出讲义。必须包含至少 4 道题，每道题按以下格式：\n"
            "题目 1：...\n题型：选择/填空/简答/应用\n答案提示：...\n解析依据：引用 [1] 或 [2]。"
        ),
        "mind_map": (
            "输出知识导图，不要输出长段讲义。必须使用以下格式：\n"
            "中心主题：...\n"
            "分支：定义 -> ...\n"
            "分支：表示方法 -> ...\n"
            "分支：常见复杂度 -> ...\n"
            "分支：相关结构 -> ...\n"
            "分支：易错点 -> ...\n"
            "分支：练习路径 -> ..."
        ),
        "extended_reading": (
            "输出拓展阅读计划。必须包含：\n"
            "阅读目标、先读材料、延伸问题、对比阅读、记录任务、资料不足提醒。"
        ),
        "coding_case": (
            "输出代码实操案例，不要输出普通讲义。必须包含：\n"
            "1. 实操目标\n2. 编程任务\n3. Python 代码块，必须使用 ```python fenced code block\n"
            "4. 输入样例\n5. 预期输出\n6. 边界条件\n7. 复杂度观察。"
        ),
        "teaching_video": (
            "输出教学动画脚本，不要输出普通讲义。必须包含：\n"
            "1. 学习目标\n2. 三段以内分镜说明\n3. 每一步状态变化的讲解重点\n"
            "4. 最终访问或操作顺序\n5. 暂停复述提示。"
        ),
    }
    return contracts.get(resource_type, contracts["guided_note"])


def _fallback_reason(exc: Exception) -> str:
    if isinstance(exc, LLMProviderError):
        return str(exc)
    if str(exc):
        return f"{type(exc).__name__}: {str(exc)[:240]}"
    return type(exc).__name__


def _elapsed_ms(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1000))
