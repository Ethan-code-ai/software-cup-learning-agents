import re
import time
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select

from app.adapters.llm_provider import LLMSettings, build_llm_provider
from app.agents.profile_updater_agents import LLMBackedProfileUpdaterAgent
from app.db.base import Base
from app.db.schema_compat import ensure_agent_run_step_columns
from app.db.session import get_engine, session_scope
from app.domain.exceptions import NotFoundError
from app.models import AgentRun, AgentRunStep, StudentProfile, StudentProfileHistory
from app.schemas import StudentProfileHistoryResponse, StudentProfileResponse
from app.services.demo_data_service import DemoDataService
from app.services.agent_execution_metadata import build_execution_metadata, sanitize_trace_text
from app.services.profile_builder import normalize_profile_dimensions
from app.schemas import StudentProfileCreate


PROFILE_DIMENSION_KEYS = [
    "learning_goal",
    "foundation_level",
    "learning_preference",
    "available_time",
    "weak_points",
    "resource_preference",
]


@dataclass(frozen=True)
class TraceEvidence:
    weak_points: list[str]
    resource_preference: str | None
    learning_preference: str | None
    foundation_level: str | None
    sources: list[dict[str, str | int]]
    analysis_method: str = "rule_based"
    reason: str | None = None
    fallback_reason: str | None = None
    execution_mode: str = "rule_based"
    provider: str = "rule_based"
    model: str = ""
    fallback_used: bool = False
    duration_ms: int = 0
    provider_metadata: dict = field(default_factory=dict)


class ProfileUpdaterService:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url

    def update_from_trace(
        self,
        profile_id: int,
        limit: int = 8,
        *,
        trigger_type: str = "manual_trace_sync",
        event_key: str | None = None,
    ) -> StudentProfileResponse:
        DemoDataService(database_url=self.database_url).get_status()
        with session_scope(self.database_url) as session:
            profile = session.get(StudentProfile, profile_id)
            if profile is None:
                raise NotFoundError("Student profile", profile_id)

            runs = session.scalars(
                select(AgentRun)
                .where(AgentRun.student_profile_id == profile_id)
                .order_by(AgentRun.id.desc())
                .limit(limit)
            ).all()
            run_ids = [run.id for run in runs]
            steps = []
            if run_ids:
                steps = session.scalars(
                    select(AgentRunStep)
                    .where(AgentRunStep.agent_run_id.in_(run_ids))
                    .order_by(AgentRunStep.agent_run_id.desc(), AgentRunStep.step_order)
                ).all()

            resolved_event_key = event_key or self._event_key(profile_id, trigger_type, steps)
            existing_history = session.scalar(
                select(StudentProfileHistory).where(StudentProfileHistory.event_key == resolved_event_key)
            )
            if existing_history is not None or not steps:
                return StudentProfileResponse.model_validate(profile)

            before_dimensions = self._profile_dimensions(profile)
            evidence = self._analyze_steps_with_optional_llm(steps)
            current_preferences = profile.preferences if isinstance(profile.preferences, dict) else {}
            next_preferences = dict(current_preferences)

            if evidence.weak_points:
                next_preferences["weak_points"] = "、".join(evidence.weak_points)
            if evidence.resource_preference:
                next_preferences["resource_preference"] = evidence.resource_preference
                next_preferences["resource"] = evidence.resource_preference
            if evidence.learning_preference:
                next_preferences["learning_preference"] = evidence.learning_preference
                next_preferences["style"] = evidence.learning_preference
            if evidence.foundation_level:
                next_preferences["foundation_level"] = evidence.foundation_level
                profile.level = evidence.foundation_level

            reason = self._build_reason(evidence, len(steps))
            next_preferences["last_profile_update_reason"] = reason
            next_preferences["last_profile_update_sources"] = evidence.sources

            normalized = normalize_profile_dimensions(
                StudentProfileCreate(
                    user_id=profile.user_id,
                    profile_type=profile.profile_type,
                    goal=profile.goal,
                    level=profile.level,
                    preferences=next_preferences,
                    time_budget=profile.time_budget,
                )
            )
            next_preferences = normalized.preferences
            after_dimensions = self._profile_dimensions(profile, next_preferences)
            changed_dimensions = [
                key for key in PROFILE_DIMENSION_KEYS if before_dimensions.get(key) != after_dimensions.get(key)
            ]
            if not changed_dimensions:
                return StudentProfileResponse.model_validate(profile)

            profile.preferences = next_preferences

            run = AgentRun(
                run_type="profile_update",
                student_profile_id=profile_id,
                course_id=None,
                status="completed",
                input_summary=f"Analyze recent {len(steps)} AgentRunStep records for profile adaptation; trigger={trigger_type}.",
                output_summary="ProfileUpdater Agent refreshed dynamic student profile dimensions.",
                final_summary="ProfileUpdater Agent completed profile update from multi-agent trace.",
                completed_at=datetime.utcnow(),
            )
            session.add(run)
            session.flush()
            session.add(
                AgentRunStep(
                    agent_run_id=run.id,
                    agent_type="profile_updater",
                    step_order=1,
                    status="completed",
                    input_summary=f"steps={len(steps)}; sources={len(evidence.sources)}; method={evidence.analysis_method}",
                    output_summary=self._profile_update_summary(evidence),
                    decision_basis=next_preferences["last_profile_update_reason"],
                    duration_ms=evidence.duration_ms,
                    execution_metadata=build_execution_metadata(
                        evidence,
                        execution_mode=evidence.execution_mode,
                        provider=evidence.provider,
                        model=evidence.model,
                        fallback_used=evidence.fallback_used,
                        fallback_reason=evidence.fallback_reason,
                        source_refs=self._evidence_source_refs(evidence.sources),
                        duration_ms=evidence.duration_ms,
                    ),
                )
            )
            next_preferences["last_profile_update_agent_run_id"] = run.id
            profile.preferences = next_preferences
            history = StudentProfileHistory(
                student_profile_id=profile_id,
                event_key=resolved_event_key,
                trigger_type=trigger_type,
                before_dimensions=before_dimensions,
                after_dimensions=self._profile_dimensions(profile, next_preferences),
                changed_dimensions=changed_dimensions,
                reason=reason,
                evidence_refs=[
                    *self._history_evidence(steps),
                    {"kind": "profile_update_agent_run", "agent_run_id": run.id, "summary": "ProfileUpdater Agent update."},
                ],
                agent_run_id=steps[0].agent_run_id if steps else run.id,
            )
            session.add(history)
            session.flush()
            return StudentProfileResponse.model_validate(profile)

    def create_initial_history(
        self,
        profile_id: int,
        evidence_summary: str,
        *,
        execution_mode: str = "rule_based",
        provider: str = "rule_based",
        model: str = "",
        fallback_reason: str | None = None,
        duration_ms: int = 0,
    ) -> StudentProfileHistoryResponse:
        Base.metadata.create_all(get_engine(self.database_url))
        ensure_agent_run_step_columns(self.database_url)
        safe_fallback_reason = sanitize_trace_text(fallback_reason, 500) or None
        with session_scope(self.database_url) as session:
            profile = session.get(StudentProfile, profile_id)
            if profile is None:
                raise NotFoundError("Student profile", profile_id)
            event_key = f"dialogue:{profile_id}"
            existing = session.scalar(select(StudentProfileHistory).where(StudentProfileHistory.event_key == event_key))
            if existing is not None:
                return StudentProfileHistoryResponse.model_validate(existing)

            dimensions = self._profile_dimensions(profile)
            run = AgentRun(
                run_type="profile_build",
                student_profile_id=profile_id,
                course_id=None,
                status="completed",
                input_summary="Build six-dimension profile from dialogue summary.",
                output_summary="Profile Builder Agent created the initial six-dimension profile.",
                final_summary="Initial profile snapshot recorded.",
                duration_ms=duration_ms,
                completed_at=datetime.utcnow(),
            )
            session.add(run)
            session.flush()
            session.add(
                AgentRunStep(
                    agent_run_id=run.id,
                    agent_type="profile_builder",
                    step_order=1,
                    status="completed",
                    input_summary="dialogue_summary_received=true",
                    output_summary="Initial six profile dimensions extracted.",
                    decision_basis=(
                        f"execution_mode={execution_mode}; provider={provider}; model={model or 'none'}; "
                        f"fallback_used={str(bool(safe_fallback_reason)).lower()}; "
                        f"fallback_reason={safe_fallback_reason or 'none'}"
                    ),
                    duration_ms=duration_ms,
                    execution_metadata=build_execution_metadata(
                        execution_mode=execution_mode,
                        provider=provider,
                        model=model,
                        fallback_used=bool(safe_fallback_reason),
                        fallback_reason=safe_fallback_reason,
                        duration_ms=duration_ms,
                    ),
                )
            )
            history = StudentProfileHistory(
                student_profile_id=profile_id,
                event_key=event_key,
                trigger_type="dialogue",
                before_dimensions={},
                after_dimensions=dimensions,
                changed_dimensions=list(PROFILE_DIMENSION_KEYS),
                reason=(
                    f"画像由对话建档结果创建，已初始化六个画像维度；execution_mode={execution_mode}。"
                    + (f" LLM 不可用，已回退：{safe_fallback_reason}。" if safe_fallback_reason else "")
                ),
                evidence_refs=[
                    {
                        "kind": "dialogue",
                        "agent_run_id": run.id,
                        "summary": evidence_summary[:300],
                    }
                ],
                agent_run_id=run.id,
            )
            session.add(history)
            session.flush()
            return StudentProfileHistoryResponse.model_validate(history)

    def list_history(self, profile_id: int, limit: int = 20) -> list[StudentProfileHistoryResponse]:
        Base.metadata.create_all(get_engine(self.database_url))
        with session_scope(self.database_url) as session:
            if session.get(StudentProfile, profile_id) is None:
                raise NotFoundError("Student profile", profile_id)
            records = session.scalars(
                select(StudentProfileHistory)
                .where(StudentProfileHistory.student_profile_id == profile_id)
                .order_by(StudentProfileHistory.created_at.desc(), StudentProfileHistory.id.desc())
                .limit(limit)
            ).all()
            return [StudentProfileHistoryResponse.model_validate(record) for record in records]

    def _profile_dimensions(self, profile: StudentProfile, preferences: dict | None = None) -> dict[str, str]:
        values = preferences if preferences is not None else (profile.preferences if isinstance(profile.preferences, dict) else {})
        return {
            "learning_goal": str(values.get("learning_goal") or profile.goal),
            "foundation_level": str(profile.level),
            "learning_preference": str(values.get("learning_preference") or "step_by_step"),
            "available_time": str(values.get("available_time") or profile.time_budget),
            "weak_points": str(values.get("weak_points") or "暂无明确薄弱点"),
            "resource_preference": str(values.get("resource_preference") or "讲解文档"),
        }

    def _event_key(self, profile_id: int, trigger_type: str, steps: list[AgentRunStep]) -> str:
        step_ids = ",".join(str(step.id) for step in steps[:8]) or "none"
        return f"{trigger_type}:{profile_id}:{step_ids}"

    def _history_evidence(self, steps: list[AgentRunStep]) -> list[dict[str, str | int]]:
        return [
            {
                "kind": "agent_step",
                "agent_run_id": step.agent_run_id,
                "agent_step_id": step.id,
                "agent_type": step.agent_type,
                "summary": step.output_summary[:160],
            }
            for step in steps[:8]
        ]

    def _analyze_steps(self, steps: list[AgentRunStep]) -> TraceEvidence:
        weak_points: list[str] = []
        sources: list[dict[str, str | int]] = []
        resource_preference: str | None = None
        learning_preference: str | None = None
        foundation_level: str | None = None

        for step in steps:
            text = " ".join([step.input_summary, step.output_summary, step.decision_basis]).lower()
            for label in self._concept_labels(text):
                if label not in weak_points:
                    weak_points.append(label)

            if step.agent_type == "resource":
                inferred_resource = self._resource_preference(text)
                if inferred_resource:
                    resource_preference = inferred_resource
                inferred_learning = self._learning_preference(text)
                if inferred_learning:
                    learning_preference = inferred_learning

            if step.agent_type == "tutor":
                for label in self._concept_labels(step.input_summary.lower()):
                    if label not in weak_points:
                        weak_points.append(label)

            if step.agent_type == "evaluator":
                score = self._score_from_text(text)
                if score is not None:
                    foundation_level = "intermediate" if score >= 0.8 else "beginner"

            if len(sources) < 8:
                sources.append(
                    {
                        "agent_run_id": step.agent_run_id,
                        "agent_step_id": step.id,
                        "agent_type": step.agent_type,
                        "summary": step.output_summary[:120],
                    }
                )

        return TraceEvidence(
            weak_points=weak_points,
            resource_preference=resource_preference,
            learning_preference=learning_preference,
            foundation_level=foundation_level,
            sources=sources,
        )

    def _analyze_steps_with_optional_llm(self, steps: list[AgentRunStep]) -> TraceEvidence:
        rule_based = self._analyze_steps(steps)
        settings = LLMSettings.from_env()
        provider = build_llm_provider(settings, purpose="profile_updater")
        if provider is None or not steps:
            return rule_based

        started = time.perf_counter()
        try:
            analysis = LLMBackedProfileUpdaterAgent(
                provider,
                provider_name=settings.provider,
                model=settings.model,
            ).analyze(self._trace_payload(steps))
        except Exception as exc:
            return TraceEvidence(
                weak_points=rule_based.weak_points,
                resource_preference=rule_based.resource_preference,
                learning_preference=rule_based.learning_preference,
                foundation_level=rule_based.foundation_level,
                sources=rule_based.sources,
                analysis_method="rule_based_fallback",
                fallback_reason=self._fallback_reason(exc),
                execution_mode="rule_based_fallback",
                provider=settings.provider,
                model=settings.model,
                fallback_used=True,
                duration_ms=max(0, round((time.perf_counter() - started) * 1000)),
                provider_metadata=getattr(exc, "metadata", {}),
            )

        return TraceEvidence(
            weak_points=analysis.weak_points,
            resource_preference=analysis.resource_preference,
            learning_preference=analysis.learning_preference,
            foundation_level=analysis.foundation_level,
            sources=rule_based.sources,
            analysis_method="llm",
            reason=analysis.reason,
            execution_mode="llm",
            provider=analysis.provider,
            model=analysis.model,
            duration_ms=analysis.duration_ms,
            provider_metadata=analysis.provider_metadata,
        )

    @staticmethod
    def _evidence_source_refs(sources: list[dict[str, str | int]]) -> list[str]:
        refs: list[str] = []
        for source in sources:
            run_id = source.get("agent_run_id")
            step_id = source.get("agent_step_id")
            if run_id is None:
                continue
            ref = f"agent-run:{run_id}"
            if step_id is not None:
                ref += f"#step:{step_id}"
            if ref not in refs:
                refs.append(ref)
        return refs[:8]

    def _trace_payload(self, steps: list[AgentRunStep]) -> list[dict[str, str | int]]:
        payload = []
        for step in steps[:8]:
            payload.append(
                {
                    "agent_run_id": step.agent_run_id,
                    "agent_type": step.agent_type,
                    "input_summary": step.input_summary[:240],
                    "output_summary": step.output_summary[:360],
                    "decision_basis": step.decision_basis[:360],
                }
            )
        return payload

    def _concept_labels(self, text: str) -> list[str]:
        labels = []
        for keyword, label in [
            ("复杂度", "复杂度分析"),
            ("链表", "链表"),
            ("栈", "栈/队列"),
            ("队列", "栈/队列"),
            ("树", "二叉树遍历"),
            ("bfs", "BFS/DFS"),
            ("dfs", "BFS/DFS"),
            ("图", "BFS/DFS"),
        ]:
            if keyword in text and label not in labels:
                labels.append(label)
        return labels

    def _resource_preference(self, text: str) -> str | None:
        if "代码实操" in text or "coding_case" in text:
            return "代码实操案例"
        if "练习题" in text or "practice_questions" in text:
            return "练习题"
        if "思维导图" in text or "mind_map" in text:
            return "思维导图"
        if "拓展阅读" in text or "extended_reading" in text:
            return "拓展阅读"
        if "讲解文档" in text or "guided_note" in text:
            return "讲解文档"
        return None

    def _learning_preference(self, text: str) -> str | None:
        if "代码实操" in text or "coding_case" in text:
            return "code_driven"
        if "练习题" in text or "practice_questions" in text:
            return "worked_examples"
        if "讲解文档" in text or "guided_note" in text:
            return "step_by_step"
        return None

    def _score_from_text(self, text: str) -> float | None:
        match = re.search(r"评分\s+([0-9]+(?:\.[0-9]+)?)", text)
        if not match:
            return None
        return float(match.group(1))

    def _build_reason(self, evidence: TraceEvidence, step_count: int) -> str:
        if step_count == 0:
            return "暂无可分析的 Agent trace，画像保持当前状态。"
        if evidence.analysis_method == "llm":
            return f"LLM ProfileUpdater 基于最近 {step_count} 个 Agent step 更新画像：{evidence.reason}"
        parts = [f"基于最近 {step_count} 个 Agent step 更新画像"]
        if evidence.weak_points:
            parts.append(f"识别关注知识点：{'、'.join(evidence.weak_points)}")
        if evidence.resource_preference:
            parts.append(f"资源偏好调整为：{evidence.resource_preference}")
        if evidence.foundation_level:
            parts.append(f"基础水平调整为：{evidence.foundation_level}")
        if evidence.fallback_reason:
            parts.append(f"LLM 分析不可用，已回退到 rule-based：{evidence.fallback_reason}")
        return "；".join(parts)

    def _profile_update_summary(self, evidence: TraceEvidence) -> str:
        changes = []
        if evidence.weak_points:
            changes.append(f"weak_points={','.join(evidence.weak_points)}")
        if evidence.resource_preference:
            changes.append(f"resource_preference={evidence.resource_preference}")
        if evidence.learning_preference:
            changes.append(f"learning_preference={evidence.learning_preference}")
        if evidence.foundation_level:
            changes.append(f"foundation_level={evidence.foundation_level}")
        if not changes:
            changes.append("no dimension change; profile context preserved")
        return f"ProfileUpdater Agent method={evidence.analysis_method}; " + "; ".join(changes)

    def _fallback_reason(self, exc: Exception) -> str:
        if str(exc):
            return sanitize_trace_text(f"{type(exc).__name__}: {str(exc)}", 500)
        return type(exc).__name__
