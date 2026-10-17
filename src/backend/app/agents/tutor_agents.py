import hashlib
import json
import re
import time
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field, ValidationError

from app.adapters.llm_provider import LLMProviderError
from app.adapters.protocols import LLMProvider
from app.agents.rule_based_agents import RuleBasedTutorAgent, TutorAgentResult
from app.agents.tutor_prompts import build_tutor_messages
from app.schemas import KnowledgeSearchResult
from app.services.citation_service import source_ref_payload, validate_citations
from app.services.content_safety_service import ContentSafetyService


class TutorAgent(Protocol):
    def answer(self, question: str, chunks: list[KnowledgeSearchResult], profile_summary: str = "", course_title: str = "") -> TutorAgentResult:
        raise NotImplementedError


@dataclass(frozen=True)
class TutorEvidence:
    evidence_id: str
    content: str
    source_ref: dict[str, Any]


class TutorSection(BaseModel):
    heading: Literal["direct_answer", "profile_adaptation", "next_step"]
    content: str = Field(min_length=1, max_length=800)
    evidence_ids: list[str] = Field(min_length=1, max_length=3)


class TutorStructuredOutput(BaseModel):
    sections: list[TutorSection] = Field(min_length=3, max_length=3)


TUTOR_OUTPUT_SCHEMA: dict[str, Any] = TutorStructuredOutput.model_json_schema()
_EXPECTED_HEADINGS = ["direct_answer", "profile_adaptation", "next_step"]


def select_tutor_evidence(chunks: list[KnowledgeSearchResult]) -> list[TutorEvidence]:
    selected: list[tuple[str, set[str], KnowledgeSearchResult]] = []
    total_chars = 0
    for chunk in chunks:
        normalized = " ".join(chunk.content.split()).strip()
        if not normalized:
            continue
        digest = hashlib.sha256(normalized.casefold().encode("utf-8")).hexdigest()
        tokens = _content_tokens(normalized)
        if any(digest == old_digest or _jaccard(tokens, old_tokens) >= 0.8 for old_digest, old_tokens, _ in selected):
            continue
        remaining = 2400 - total_chars
        if remaining <= 0 or len(selected) >= 3:
            break
        content = normalized[: min(900, remaining)]
        selected.append((digest, tokens, chunk.model_copy(update={"content": content})))
        total_chars += len(content)
    return [
        TutorEvidence(f"E{index}", item.content, source_ref_payload(item))
        for index, (_, _, item) in enumerate(selected, start=1)
    ]


class LLMBackedTutorAgent:
    def __init__(self, provider: LLMProvider, fallback_agent: RuleBasedTutorAgent | None = None, fallback_mode: str = "rule_based", provider_name: str = "openai_compatible", model: str = "") -> None:
        self.provider = provider
        self.fallback_agent = fallback_agent or RuleBasedTutorAgent()
        self.fallback_mode = fallback_mode if fallback_mode in {"rule_based", "error"} else "rule_based"
        self.provider_name = provider_name
        self.model = model

    def answer(self, question: str, chunks: list[KnowledgeSearchResult], profile_summary: str = "", course_title: str = "") -> TutorAgentResult:
        started = time.perf_counter()
        evidence = select_tutor_evidence(chunks)
        diagnostics = {
            "retrieved_count": len(chunks),
            "selected_evidence_count": len(evidence),
            "context_chars": sum(len(item.content) for item in evidence),
            "evidence_ids_used": [],
        }
        if not evidence:
            return self._fallback(question, chunks, profile_summary, course_title, "No retrieved course chunks are available.", started, diagnostics)
        try:
            result = self.provider.generate(
                build_tutor_messages(question, evidence, profile_summary, course_title),
                response_schema=TUTOR_OUTPUT_SCHEMA,
            )
            pre_safety = ContentSafetyService().review_output(
                result.content,
                allowed_source_refs={str(item.source_ref.get("source_ref")) for item in evidence if item.source_ref.get("source_ref")},
            )
            if not pre_safety.allowed and pre_safety.category == "dangerous_code":
                raise ValueError(f"Content safety blocked LLM output: {pre_safety.category}")
            if _contradicts_retrieved_context(result.content):
                raise ValueError("LLM answer contradicted non-empty retrieved chunks.")
            parsed, structure_repaired = _parse_tutor_output(result.content, [item.evidence_id for item in evidence])
            if [section.heading for section in parsed.sections] != _EXPECTED_HEADINGS:
                raise ValueError("Tutor sections must use the required order.")
            if "document:" in result.content.lower() or "chunk:" in result.content.lower():
                raise ValueError("Tutor output exposed an internal source reference.")
            output_safety = ContentSafetyService().review_output(result.content, allowed_source_refs=set())
            if not output_safety.allowed:
                raise ValueError(f"Content safety blocked LLM output: {output_safety.category}")
            evidence_by_id = {item.evidence_id: item for item in evidence}
            used_ids: list[str] = []
            for section in parsed.sections:
                unknown = [item for item in section.evidence_ids if item not in evidence_by_id]
                if unknown:
                    raise ValueError(f"Tutor output cited unknown evidence IDs: {', '.join(unknown)}")
                for evidence_id in section.evidence_ids:
                    if evidence_id not in used_ids:
                        used_ids.append(evidence_id)
            source_refs = [evidence_by_id[item].source_ref for item in used_ids]
            answer = _render_tutor_answer(parsed, evidence_by_id)
            citation_check = validate_citations(answer, source_refs)
            if citation_check["fake_source_refs"] or citation_check["missing_citation"]:
                raise ValueError("Mapped Tutor citations failed the final whitelist validation.")
            metadata = dict(result.metadata)
            metadata.update(diagnostics)
            metadata["evidence_ids_used"] = used_ids
            if structure_repaired:
                metadata["structure_repaired"] = "flat_sections"
            return TutorAgentResult(
                answer=answer,
                source_refs=source_refs,
                input_summary=f"使用 {len(evidence)} 条压缩证据回答学生问题。",
                output_summary="LLM 返回结构化中文辅导答复，证据 ID 已映射并通过引用白名单校验。",
                decision_basis="模型仅可见 E1-E3；后端负责真实 source_ref 映射和最终引用校验。",
                execution_mode="llm",
                provider=str(result.metadata.get("provider") or self.provider_name),
                model=str(result.metadata.get("model") or self.model),
                duration_ms=_elapsed_ms(started),
                provider_metadata=metadata,
            )
        except Exception as exc:
            reason = _fallback_reason(exc)
            if self.fallback_mode == "error":
                raise LLMProviderError(reason) from exc
            return self._fallback(question, chunks, profile_summary, course_title, reason, started, diagnostics, exc)

    def _fallback(self, question: str, chunks: list[KnowledgeSearchResult], profile_summary: str, course_title: str, reason: str, started: float, diagnostics: dict[str, Any], exc: Exception | None = None) -> TutorAgentResult:
        fallback = self.fallback_agent.answer(question, chunks, profile_summary, course_title)
        answer = (
            f"本次模型回答未能通过稳定性或安全校验，已切换为安全降级。"
            f"请根据下方可追溯课程资料核对“{question}”的定义、适用场景和示例；系统未在主回答中复述未经生成校验的原文。"
            if chunks else f"暂未检索到足够资料回答“{question}”，请先补充或重新索引相关课程资料。"
        )
        metadata = dict(getattr(exc, "metadata", {}) or {})
        metadata.update(diagnostics)
        return TutorAgentResult(
            answer=answer,
            source_refs=fallback.source_refs,
            input_summary=fallback.input_summary,
            output_summary="LLM 调用或结构化校验失败，已回退到 rule-based 中文安全降级说明。",
            decision_basis=f"{fallback.decision_basis} Fallback reason: {reason}.",
            execution_mode="rule_based_fallback",
            provider=self.provider_name,
            model=self.model,
            fallback_used=True,
            fallback_reason=reason,
            duration_ms=_elapsed_ms(started),
            provider_metadata=metadata,
        )


def _render_tutor_answer(output: TutorStructuredOutput, evidence_by_id: dict[str, TutorEvidence]) -> str:
    headings = {"direct_answer": "直接回答", "profile_adaptation": "结合你的画像", "next_step": "下一步练习"}
    sections = []
    for section in output.sections:
        refs = []
        for evidence_id in section.evidence_ids:
            source_ref = evidence_by_id[evidence_id].source_ref.get("source_ref")
            if source_ref and source_ref not in refs:
                refs.append(str(source_ref))
        citations = " ".join(f"[{item}]" for item in refs)
        sections.append(f"### {headings[section.heading]}\n\n{section.content} {citations}".rstrip())
    return "\n\n".join(sections)


def _content_tokens(content: str) -> set[str]:
    lowered = content.casefold()
    words = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", lowered)
    return set(words)


def _extract_json_object(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1)
    start, end = stripped.find("{"), stripped.rfind("}")
    if start != -1 and end > start:
        return stripped[start : end + 1]
    raise ValueError("Tutor response did not contain a JSON object.")


def _parse_tutor_output(content: str, evidence_ids: list[str]) -> tuple[TutorStructuredOutput, bool]:
    payload = json.loads(_extract_json_object(content))
    if isinstance(payload, dict) and "sections" in payload:
        return TutorStructuredOutput.model_validate(payload), False
    if (
        isinstance(payload, dict)
        and set(payload) == set(_EXPECTED_HEADINGS)
        and all(isinstance(payload[heading], str) and payload[heading].strip() for heading in _EXPECTED_HEADINGS)
    ):
        normalized = {
            "sections": [
                {"heading": heading, "content": payload[heading].strip(), "evidence_ids": evidence_ids}
                for heading in _EXPECTED_HEADINGS
            ]
        }
        return TutorStructuredOutput.model_validate(normalized), True
    return TutorStructuredOutput.model_validate(payload), False


def _contradicts_retrieved_context(answer: str) -> bool:
    normalized = answer.casefold()
    return any(marker in normalized for marker in (
        "no retrieved course chunks", "no retrieved chunks", "没有检索到", "无法依据课程资料", "资料不足"
    ))


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 1.0


def _fallback_reason(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        fields = sorted(
            f"{'.'.join(str(part) for part in error['loc'])}:{error['type']}"
            for error in exc.errors()
        )
        return f"ValidationError: Tutor schema validation failed ({','.join(fields[:6])})"
    if isinstance(exc, LLMProviderError):
        return str(exc)
    return f"{type(exc).__name__}: {str(exc)[:240]}" if str(exc) else type(exc).__name__


def _elapsed_ms(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1000))
