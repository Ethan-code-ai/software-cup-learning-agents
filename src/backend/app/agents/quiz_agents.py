import json
import re
import time
from dataclasses import dataclass, field, replace
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field, ValidationError

from app.adapters.llm_provider import LLMProviderError
from app.adapters.protocols import LLMProvider
from app.agents.rule_based_agents import QuizAgentResult, RuleBasedQuizAgent
from app.schemas import KnowledgeSearchResult
from app.services.citation_service import source_ref_payload
from app.services.content_safety_service import ContentSafetyService


QuestionType = Literal["multiple_choice", "fill_blank", "short_answer", "application", "code_analysis"]


@dataclass(frozen=True)
class QuizContext:
    profile_preferences: dict[str, Any] = field(default_factory=dict)
    mastery_score: float | None = None
    recent_errors: list[str] = field(default_factory=list)


class QuizOutput(BaseModel):
    question_type: QuestionType
    question: str = Field(min_length=1, max_length=2000)
    options: list[str] = Field(default_factory=list, max_length=8)
    answer: str = Field(min_length=1, max_length=2000)
    explanation: str = Field(min_length=1, max_length=4000)
    difficulty: str = Field(min_length=1, max_length=40)
    concept_tags: list[str] = Field(min_length=1, max_length=8)
    source_refs: list[str] = Field(min_length=1, max_length=5)


QUIZ_OUTPUT_SCHEMA: dict[str, Any] = QuizOutput.model_json_schema()


class QuizAgent(Protocol):
    def generate(
        self,
        concept_name: str,
        difficulty: str,
        chunks: list[KnowledgeSearchResult],
        context: QuizContext,
    ) -> QuizAgentResult:
        raise NotImplementedError


class LLMQuizAgent:
    def __init__(
        self,
        provider: LLMProvider,
        fallback_agent: RuleBasedQuizAgent | None = None,
        fallback_mode: str = "rule_based",
        provider_name: str = "openai_compatible",
        model: str = "",
    ) -> None:
        self.provider = provider
        self.fallback_agent = fallback_agent or RuleBasedQuizAgent()
        self.fallback_mode = fallback_mode if fallback_mode in {"rule_based", "error"} else "rule_based"
        self.provider_name = provider_name
        self.model = model

    def generate(
        self,
        concept_name: str,
        difficulty: str,
        chunks: list[KnowledgeSearchResult],
        context: QuizContext,
    ) -> QuizAgentResult:
        started = time.perf_counter()
        allowed_sources = {chunk.source_ref: chunk for chunk in chunks if chunk.source_ref}
        if not allowed_sources:
            return self._fallback(
                concept_name,
                difficulty,
                chunks,
                context,
                "No grounded retrieval source was available for Quiz generation.",
                started,
            )
        try:
            safety = ContentSafetyService().review_input(
                " ".join(
                    [
                        concept_name,
                        difficulty,
                        json.dumps(context.profile_preferences, ensure_ascii=False, default=str),
                        " ".join(context.recent_errors),
                    ]
                )
            )
            if not safety.allowed:
                raise ValueError(f"Content safety blocked input: {safety.category}")
            result = self.provider.generate(
                _build_quiz_messages(concept_name, difficulty, chunks, context),
                response_schema=QUIZ_OUTPUT_SCHEMA,
            )
            parsed = _normalize_multiple_choice_answer(_parse_quiz_output(result.content))
            _validate_quiz_output(parsed, difficulty, set(allowed_sources))
            source_refs = [source_ref_payload(allowed_sources[source_ref]) for source_ref in parsed.source_refs]
            provider = str(result.metadata.get("provider") or self.provider_name)
            model = str(result.metadata.get("model") or self.model)
            duration_ms = _elapsed_ms(started)
            return QuizAgentResult(
                question=parsed.question,
                answer=parsed.answer,
                explanation=parsed.explanation,
                concept_tags=parsed.concept_tags,
                input_summary=f"为知识点 {concept_name} 生成 {difficulty} 难度的个性化 {parsed.question_type} 题目。",
                output_summary=f"LLM Quiz Agent 生成 {parsed.question_type} 题目并绑定 {len(source_refs)} 个真实引用。",
                decision_basis=(
                    f"execution_mode=llm; provider={provider}; model={model or 'none'}; fallback_used=false; "
                    f"question_type={parsed.question_type}; source_refs={','.join(parsed.source_refs)}"
                ),
                question_type=parsed.question_type,
                options=parsed.options,
                source_refs=source_refs,
                execution_mode="llm",
                provider=provider,
                model=model,
                duration_ms=duration_ms,
                provider_metadata=result.metadata,
            )
        except Exception as exc:
            reason = _fallback_reason(exc)
            if self.fallback_mode == "error":
                raise LLMProviderError(reason) from exc
            return self._fallback(
                concept_name,
                difficulty,
                chunks,
                context,
                reason,
                started,
                getattr(exc, "metadata", {}),
            )

    def _fallback(
        self,
        concept_name: str,
        difficulty: str,
        chunks: list[KnowledgeSearchResult],
        context: QuizContext,
        reason: str,
        started: float,
        provider_metadata: dict[str, Any] | None = None,
    ) -> QuizAgentResult:
        if self.fallback_mode == "error":
            raise LLMProviderError(reason)
        fallback = self.fallback_agent.generate(concept_name, difficulty, chunks, context)
        return replace(
            fallback,
            output_summary="LLM Quiz Agent 不可用，已回退到 rule-based Quiz Agent。",
            decision_basis=(
                f"{fallback.decision_basis} execution_mode=rule_based_fallback; provider={self.provider_name}; "
                f"model={self.model or 'none'}; fallback_used=true; fallback_reason={reason}; "
                f"source_refs={','.join(str(item.get('source_ref')) for item in fallback.source_refs)}"
            ),
            execution_mode="rule_based_fallback",
            provider=self.provider_name,
            model=self.model,
            fallback_used=True,
            fallback_reason=reason,
            duration_ms=_elapsed_ms(started),
            provider_metadata=provider_metadata or {},
        )


def _build_quiz_messages(
    concept_name: str,
    difficulty: str,
    chunks: list[KnowledgeSearchResult],
    context: QuizContext,
) -> list[dict[str, str]]:
    evidence = [
        {
            "source_ref": chunk.source_ref,
            "content": chunk.content[:1800],
        }
        for chunk in chunks[:3]
        if chunk.source_ref
    ]
    student_context = {
        "profile": context.profile_preferences,
        "mastery_score": context.mastery_score,
        "recent_errors": context.recent_errors[:5],
    }
    return [
        {
            "role": "system",
            "content": (
                "你是数据结构课程的 Quiz Agent。只能依据给定课程证据出题，不得使用或编造其他 source_ref。"
                "根据学生画像、掌握度和最近错误选择 multiple_choice、fill_blank、short_answer、application、"
                "code_analysis 之一。所有面向学生的自然语言必须使用简体中文，包括 question、options、"
                "answer 和 explanation；BFS、DFS、Queue、复杂度记号及代码等专业符号可以保留英文。"
                "只返回 JSON object，不输出 Markdown。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"JSON schema：{json.dumps(QUIZ_OUTPUT_SCHEMA, ensure_ascii=False)}\n"
                f"知识点：{concept_name}\n"
                f"目标难度（difficulty 必须原样返回）：{difficulty}\n"
                f"学生上下文：{json.dumps(student_context, ensure_ascii=False)}\n"
                f"课程证据：{json.dumps(evidence, ensure_ascii=False)}\n"
                "multiple_choice 必须提供 2 至 8 个带 A./B. 前缀的选项，answer 返回正确选项字母；其他题型 options=[]。"
                "选择题每个选项的说明文字必须包含中文，不得生成全英文题干、选项或解析。"
                "code_analysis 的 question 必须包含 fenced code block。"
                "explanation 必须解释答案并对应课程证据；source_refs 只能从课程证据原样选择，至少一个。"
            ),
        },
    ]


def _parse_quiz_output(content: str) -> QuizOutput:
    raw = _extract_json_object(content)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Quiz response contained invalid JSON.") from exc
    try:
        return QuizOutput.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(f"Quiz response failed schema validation: {exc.errors()[0]['type']}") from exc


def _normalize_multiple_choice_answer(output: QuizOutput) -> QuizOutput:
    if output.question_type != "multiple_choice":
        return output
    answer = output.answer.strip()
    direct_label = re.fullmatch(r"([A-Ha-h])(?:[.、。:]?)", answer)
    if direct_label:
        return output.model_copy(update={"answer": direct_label.group(1).upper()})

    normalized_answer = re.sub(r"\s+", "", answer).casefold()
    matching_labels: list[str] = []
    for option in output.options:
        match = re.match(r"\s*([A-Ha-h])[.、。:]?\s*(.*)", option, flags=re.DOTALL)
        if not match:
            continue
        label, option_text = match.group(1).upper(), match.group(2)
        normalized_option = re.sub(r"\s+", "", option).casefold()
        normalized_text = re.sub(r"\s+", "", option_text).casefold()
        if normalized_answer in {normalized_option, normalized_text}:
            matching_labels.append(label)
    if len(matching_labels) == 1:
        return output.model_copy(update={"answer": matching_labels[0]})
    return output


def _validate_quiz_output(output: QuizOutput, difficulty: str, allowed_source_refs: set[str]) -> None:
    if not _contains_chinese_natural_language(output.question):
        raise ValueError("Quiz question must use Chinese natural language.")
    if not _contains_chinese_natural_language(output.explanation):
        raise ValueError("Quiz explanation must use Chinese natural language.")
    if output.difficulty != difficulty:
        raise ValueError("Quiz output difficulty does not match the requested difficulty.")
    if len(output.source_refs) != len(set(output.source_refs)):
        raise ValueError("Quiz output contains duplicate source references.")
    if not set(output.source_refs).issubset(allowed_source_refs):
        raise ValueError("Quiz output contains a fabricated source reference.")
    cited_in_text = set(re.findall(r"document:\d+#chunk:\d+", f"{output.question}\n{output.explanation}"))
    if not cited_in_text.issubset(set(output.source_refs)):
        raise ValueError("Quiz text contains a fabricated or undeclared source reference.")
    if output.question_type == "multiple_choice":
        if not 2 <= len(output.options) <= 8:
            raise ValueError("Multiple-choice quiz must contain between 2 and 8 options.")
        labels = {option.strip()[:1].upper() for option in output.options if option.strip()}
        if output.answer.strip().upper() not in labels:
            raise ValueError("Multiple-choice answer must match an option label.")
        if any(not _contains_chinese_natural_language(option) for option in output.options):
            raise ValueError("Multiple-choice options must use Chinese natural language.")
    elif output.options:
        raise ValueError("Only multiple-choice quizzes may contain options.")
    if output.question_type == "code_analysis" and "```" not in output.question:
        raise ValueError("Code-analysis quiz must contain a fenced code block in the question.")


def _contains_chinese_natural_language(value: str) -> bool:
    without_code = re.sub(r"```.*?```", "", value, flags=re.DOTALL)
    return re.search(r"[\u4e00-\u9fff]", without_code) is not None


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
    raise ValueError("Quiz response did not contain a JSON object.")


def _fallback_reason(exc: Exception) -> str:
    if isinstance(exc, LLMProviderError):
        return str(exc)
    return f"{type(exc).__name__}: {str(exc)[:240]}" if str(exc) else type(exc).__name__


def _elapsed_ms(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1000))
