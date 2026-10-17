import json
import re
import time
from typing import Any, Protocol

from app.adapters.llm_provider import LLMProviderError
from app.adapters.protocols import LLMProvider
from app.agents.rule_based_agents import EvaluatorAgentResult, RuleBasedEvaluatorAgent
from app.services.content_safety_service import ContentSafetyService


class EvaluatorAgent(Protocol):
    def evaluate(self, expected_answer: str, answers: dict[str, Any], concept_id: int) -> EvaluatorAgentResult:
        raise NotImplementedError


class LLMBackedEvaluatorAgent:
    def __init__(
        self,
        provider: LLMProvider,
        fallback_agent: RuleBasedEvaluatorAgent | None = None,
        fallback_mode: str = "rule_based",
        provider_name: str = "openai_compatible",
        model: str = "",
    ) -> None:
        self.provider = provider
        self.fallback_agent = fallback_agent or RuleBasedEvaluatorAgent()
        self.fallback_mode = fallback_mode if fallback_mode in {"rule_based", "error"} else "rule_based"
        self.provider_name = provider_name
        self.model = model

    def evaluate(self, expected_answer: str, answers: dict[str, Any], concept_id: int) -> EvaluatorAgentResult:
        started = time.perf_counter()
        try:
            safety = ContentSafetyService().review_input(json.dumps(answers, ensure_ascii=False, default=str))
            if not safety.allowed:
                raise ValueError(f"Content safety blocked input: {safety.category}")
            result = self.provider.generate(
                _build_evaluator_messages(expected_answer, answers, concept_id),
                response_schema=dict,
            )
            parsed = _parse_evaluation_result(result.content, concept_id)
            provider = str(result.metadata.get("provider") or self.provider_name)
            model = str(result.metadata.get("model") or self.model)
            return EvaluatorAgentResult(
                score=parsed["score"],
                feedback=parsed["feedback"],
                mastery_updates=[
                    {
                        "concept_id": concept_id,
                        "mastery_score": parsed["score"],
                        "evidence": {
                            "analysis_method": "llm",
                            "weak_points": parsed["weak_points"],
                            "misconceptions": parsed["misconceptions"],
                            "next_action": parsed["next_action"],
                        },
                    }
                ],
                input_summary=f"使用真实 LLM 评价 concept_id={concept_id} 的一次作答。",
                output_summary=f"LLM Evaluator 返回评分 {parsed['score']:.2f}、薄弱点和下一步建议。",
                decision_basis="通过 LLMProvider adapter 调用 OpenAI-compatible provider，并要求按固定 JSON schema 评价学生作答。",
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
            fallback = self.fallback_agent.evaluate(expected_answer, answers, concept_id)
            return EvaluatorAgentResult(
                score=fallback.score,
                feedback=fallback.feedback,
                mastery_updates=fallback.mastery_updates,
                input_summary=fallback.input_summary,
                output_summary="LLM provider 不可用，已回退到 rule-based evaluator。",
                decision_basis=f"{fallback.decision_basis} Fallback reason: {reason}.",
                execution_mode="rule_based_fallback",
                provider=self.provider_name,
                model=self.model,
                fallback_used=True,
                fallback_reason=reason,
                duration_ms=_elapsed_ms(started),
                provider_metadata=getattr(exc, "metadata", {}),
            )


def _build_evaluator_messages(expected_answer: str, answers: dict[str, Any], concept_id: int) -> list[dict[str, str]]:
    schema = {
        "score": "number between 0 and 1",
        "feedback": "Chinese feedback for the student",
        "weak_points": ["Chinese weak point labels"],
        "misconceptions": ["Chinese misconception descriptions"],
        "next_action": "one Chinese next-step learning action",
    }
    return [
        {
            "role": "system",
            "content": (
                "你是数据结构课程的 Evaluator Agent。请基于标准答案和学生作答进行学习效果评价。"
                "只返回 JSON object，不要输出 Markdown。评分必须在 0 到 1 之间。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"JSON schema: {json.dumps(schema, ensure_ascii=False)}\n"
                f"concept_id: {concept_id}\n"
                f"expected_answer: {expected_answer}\n"
                f"student_answers: {json.dumps(answers, ensure_ascii=False)}"
            ),
        },
    ]


def _parse_evaluation_result(content: str, concept_id: int) -> dict[str, Any]:
    parsed = json.loads(_extract_json_object(content))
    if not isinstance(parsed, dict):
        raise ValueError("Evaluator response must be a JSON object.")
    score = _score(parsed.get("score"))
    feedback = _text(parsed.get("feedback")) or f"已完成 concept_id={concept_id} 的学习效果评估。"
    return {
        "score": score,
        "feedback": feedback,
        "weak_points": _text_list(parsed.get("weak_points")),
        "misconceptions": _text_list(parsed.get("misconceptions")),
        "next_action": _text(parsed.get("next_action")) or "回看讲解资源并补做一道相关练习。",
    }


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


def _score(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise ValueError("score must be numeric.") from None
    return min(1.0, max(0.0, parsed))


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()][:5]


def _fallback_reason(exc: Exception) -> str:
    if isinstance(exc, LLMProviderError):
        return str(exc)
    if str(exc):
        return f"{type(exc).__name__}: {str(exc)[:240]}"
    return type(exc).__name__


def _elapsed_ms(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1000))
