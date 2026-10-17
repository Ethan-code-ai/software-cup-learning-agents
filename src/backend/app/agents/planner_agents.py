import json
import re
import time
from dataclasses import dataclass, field, replace
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from app.adapters.llm_provider import LLMProviderError, LLMSettings, build_llm_provider
from app.adapters.protocols import LLMProvider
from app.domain.exceptions import GoalResolutionError
from app.services.content_safety_service import ContentSafetyService


ResourceType = Literal["guided_note", "practice_questions", "mind_map", "extended_reading", "coding_case"]
ActivityType = Literal["explanation", "concept_comparison", "worked_example", "coding", "error_review", "mock_assessment", "visual_map"]
NodeRole = Literal["target", "prerequisite"]
FOCUSED_PATH_MAX_NODES = 8


class LearningIntent(BaseModel):
    purpose: Literal["concept_learning", "assessment_preparation", "project_application", "interview_preparation", "skill_consolidation"]
    action: Literal["learn", "consolidate", "rapid_review", "remediate", "practice"]
    assessment_type: Literal["course_quiz", "final_exam", "interview", "none"]
    time_horizon: Literal["immediate", "short_term", "long_term"]
    preferred_activities: list[ActivityType] = Field(min_length=1, max_length=7)
    desired_outcome: str = Field(min_length=1, max_length=300)


class GoalResolution(BaseModel):
    course_scope: Literal["focused", "full_course"] = "focused"
    target_concept_ids: list[int] = Field(min_length=1, max_length=100)
    optional_support_concept_ids: list[int] = Field(default_factory=list, max_length=2)
    learning_intent: LearningIntent
    confidence: float = Field(ge=0, le=1)


GOAL_RESOLUTION_SCHEMA = GoalResolution.model_json_schema()


class GoalResolutionWire(BaseModel):
    course_scope: Literal["focused", "full_course"] = "focused"
    target_concept_ids: list[int] = Field(min_length=1, max_length=100)
    optional_support_concept_ids: list[int] = Field(default_factory=list, max_length=2)
    purpose: Literal["concept_learning", "assessment_preparation", "project_application", "interview_preparation", "skill_consolidation"]
    action: Literal["learn", "consolidate", "rapid_review", "remediate", "practice"]
    assessment_type: Literal["course_quiz", "final_exam", "interview", "none"]
    time_horizon: Literal["immediate", "short_term", "long_term"]
    preferred_activities: list[ActivityType] = Field(min_length=1, max_length=7)
    desired_outcome: str = Field(min_length=1, max_length=300)
    confidence: float = Field(ge=0, le=1)


GOAL_RESOLUTION_WIRE_SCHEMA = GoalResolutionWire.model_json_schema()


@dataclass(frozen=True)
class PlannerConcept:
    id: int
    slug: str
    name: str
    chapter: str
    difficulty: str
    description: str = ""


@dataclass(frozen=True)
class PlannerRelation:
    source_concept_id: int
    target_concept_id: int
    relation_type: str = "prerequisite"


@dataclass(frozen=True)
class PlannerContext:
    goal: str
    profile_type: str
    foundation_level: str
    learning_preference: str
    available_time: str
    weak_points: list[str]
    resource_preference: str
    completed_concept_ids: set[int] = field(default_factory=set)
    mastery_scores: dict[int, float] = field(default_factory=dict)
    preserve_candidate_set: bool = False
    learning_goal: str = ""
    recent_errors: list[str] = field(default_factory=list)
    persisted_learning_intent: LearningIntent | None = None
    persisted_target_concept_ids: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class SelectedPlannerConcept:
    concept: PlannerConcept
    node_role: NodeRole


@dataclass(frozen=True)
class PlannerRecommendation:
    concept_id: int
    recommended_resource_type: str
    reason: str
    priority: int
    node_role: str = "target"
    activity_type: str = "explanation"
    objective: str = ""
    estimated_minutes: int = 20
    success_criterion: str = "能够独立说明核心概念并完成一道对应练习。"


@dataclass(frozen=True)
class PlannerPhaseTrace:
    phase: str
    execution_mode: str
    fallback_reason: str | None = None
    warning_reason: str | None = None


class PlannerMilestone(BaseModel):
    milestone_type: Literal["mock_assessment"]
    title: str = Field(min_length=1, max_length=160)
    objective: str = Field(min_length=1, max_length=300)
    covered_concept_ids: list[int] = Field(min_length=1, max_length=100)
    estimated_minutes: int = Field(ge=5, le=60)
    success_criterion: str = Field(min_length=1, max_length=300)


@dataclass(frozen=True)
class PlannerResult:
    recommendations: list[PlannerRecommendation]
    execution_mode: str
    provider: str
    model: str
    fallback_used: bool
    fallback_reason: str | None
    duration_ms: int
    warning_reason: str | None = None
    provider_metadata: dict[str, Any] = field(default_factory=dict)
    learning_intent: LearningIntent | None = None
    target_concept_ids: list[int] = field(default_factory=list)
    intent_confidence: float = 0
    phase_traces: list[PlannerPhaseTrace] = field(default_factory=list)
    milestones: list[PlannerMilestone] = field(default_factory=list)


class ActivityOutputItem(BaseModel):
    concept_id: int
    node_role: NodeRole
    activity_type: ActivityType
    objective: str = Field(min_length=1, max_length=300)
    estimated_minutes: int = Field(ge=5, le=60)
    success_criterion: str = Field(min_length=1, max_length=300)
    recommended_resource_type: ResourceType
    reason: str = Field(min_length=1, max_length=300)
    priority: int = Field(ge=1)


class ActivityOutput(BaseModel):
    activities: list[ActivityOutputItem] = Field(min_length=1, max_length=8)


ACTIVITY_OUTPUT_SCHEMA = ActivityOutput.model_json_schema()


class PlannerAgent(Protocol):
    def plan(self, concepts: list[PlannerConcept], relations: list[PlannerRelation], context: PlannerContext) -> PlannerResult:
        raise NotImplementedError


class RuleBasedHybridPlannerAgent:
    def plan(self, concepts: list[PlannerConcept], relations: list[PlannerRelation], context: PlannerContext) -> PlannerResult:
        started = time.perf_counter()
        resolution = _resolution_for_context(concepts, context)
        selected = select_minimal_path(
            concepts, relations, resolution.target_concept_ids, resolution.optional_support_concept_ids, context, resolution.learning_intent
        )
        recommendations = _fallback_activities(selected, resolution.learning_intent, context)
        milestones = _build_path_milestones(resolution.learning_intent, resolution.target_concept_ids, context)
        return PlannerResult(
            recommendations, "rule_based", "rule_based", "", False, None, _elapsed_ms(started),
            learning_intent=resolution.learning_intent,
            target_concept_ids=resolution.target_concept_ids,
            intent_confidence=resolution.confidence,
            phase_traces=[PlannerPhaseTrace("goal_resolution", "rule_based"), PlannerPhaseTrace("constraint_validation", "rule_based"), PlannerPhaseTrace("activity_generation", "rule_based")],
            milestones=milestones,
        )


class HybridPlannerAgent:
    def __init__(self, provider: LLMProvider, fallback_agent: PlannerAgent | None = None, fallback_mode: str = "rule_based", provider_name: str = "openai_compatible", model: str = "") -> None:
        self.provider = provider
        self.fallback_agent = fallback_agent or RuleBasedHybridPlannerAgent()
        self.fallback_mode = fallback_mode if fallback_mode in {"rule_based", "error"} else "rule_based"
        self.provider_name = provider_name
        self.model = model

    def plan(self, concepts: list[PlannerConcept], relations: list[PlannerRelation], context: PlannerContext) -> PlannerResult:
        started = time.perf_counter()
        safety = ContentSafetyService().review_input(" ".join([context.goal, context.learning_goal, *context.weak_points, *context.recent_errors]))
        if not safety.allowed:
            raise GoalResolutionError("学习目标包含无法安全处理的内容，请改写后重试。")
        phase_traces: list[PlannerPhaseTrace] = []
        fallback_reasons: list[str] = []
        warning_reasons: list[str] = []
        provider_metadata: dict[str, Any] = {}
        try:
            if context.preserve_candidate_set and context.persisted_learning_intent and context.persisted_target_concept_ids:
                resolution = GoalResolution(
                    target_concept_ids=context.persisted_target_concept_ids,
                    learning_intent=context.persisted_learning_intent,
                    confidence=1.0,
                )
                phase_traces.append(PlannerPhaseTrace("goal_resolution", "rule_based"))
            else:
                raw = self.provider.generate(_goal_resolution_messages(concepts, context), response_schema=GOAL_RESOLUTION_WIRE_SCHEMA)
                provider_metadata.update(raw.metadata)
                resolution = _parse_goal_resolution(raw.content)
                anchored_resolution = _apply_explicit_target_anchors(resolution, context.goal, concepts)
                if anchored_resolution.target_concept_ids != resolution.target_concept_ids:
                    warning_reasons.append("target_anchors_repaired")
                resolution = anchored_resolution
                _validate_resolution(resolution, concepts, context.goal)
                if resolution.course_scope == "full_course":
                    resolution = resolution.model_copy(
                        update={"target_concept_ids": [concept.id for concept in concepts]}
                    )
                phase_traces.append(PlannerPhaseTrace(
                    "goal_resolution",
                    "llm",
                    warning_reason="; ".join(warning_reasons) or None,
                ))
        except GoalResolutionError:
            raise
        except Exception as exc:
            reason = _fallback_reason(exc)
            try:
                resolution = resolve_goal_deterministically(context.goal, concepts)
            except GoalResolutionError:
                raise GoalResolutionError() from exc
            fallback_reasons.append(f"goal_resolution: {reason}")
            phase_traces.append(PlannerPhaseTrace("goal_resolution", "rule_based_fallback", reason))

        selected = select_minimal_path(
            concepts, relations, resolution.target_concept_ids, resolution.optional_support_concept_ids, context, resolution.learning_intent
        )
        phase_traces.append(PlannerPhaseTrace("constraint_validation", "rule_based"))
        milestones = _build_path_milestones(resolution.learning_intent, resolution.target_concept_ids, context)
        try:
            raw = self.provider.generate(_activity_messages(selected, resolution.learning_intent, context), response_schema=ACTIVITY_OUTPUT_SCHEMA)
            provider_metadata.update(raw.metadata)
            activities, activity_warnings = _parse_activity_output(raw.content)
            warning_reasons.extend(activity_warnings)
            activities, focus_warnings = _rebalance_assessment_minutes(
                activities,
                selected,
                resolution.learning_intent,
                context,
                reserved_minutes=sum(item.estimated_minutes for item in milestones),
            )
            warning_reasons.extend(focus_warnings)
            recommendations = _validate_and_convert_activities(
                activities,
                selected,
                context,
                resolution.learning_intent,
                reserved_minutes=sum(item.estimated_minutes for item in milestones),
            )
            phase_traces.append(PlannerPhaseTrace("activity_generation", "llm"))
        except Exception as exc:
            reason = _fallback_reason(exc)
            if self.fallback_mode == "error":
                raise LLMProviderError(reason) from exc
            recommendations = _fallback_activities(selected, resolution.learning_intent, context)
            fallback_reasons.append(f"activity_generation: {reason}")
            phase_traces.append(PlannerPhaseTrace("activity_generation", "rule_based_fallback", reason))

        fallback_used = bool(fallback_reasons)
        return PlannerResult(
            recommendations=recommendations,
            execution_mode="rule_based_fallback" if fallback_used else "llm",
            provider=self.provider_name,
            model=self.model,
            fallback_used=fallback_used,
            fallback_reason="; ".join(fallback_reasons) or None,
            duration_ms=_elapsed_ms(started),
            warning_reason="; ".join(warning_reasons) or None,
            provider_metadata=provider_metadata,
            learning_intent=resolution.learning_intent,
            target_concept_ids=resolution.target_concept_ids,
            intent_confidence=resolution.confidence,
            phase_traces=phase_traces,
            milestones=milestones,
        )


def build_planner_agent(settings: LLMSettings | None = None) -> PlannerAgent:
    resolved = settings or LLMSettings.from_env()
    provider = build_llm_provider(resolved, purpose="planner")
    if provider is None:
        return RuleBasedHybridPlannerAgent()
    return HybridPlannerAgent(provider, fallback_mode=resolved.fallback_mode, provider_name=resolved.provider, model=resolved.model)


_ALIASES: dict[str, tuple[str, ...]] = {
    "bfs-dfs": ("图搜索", "图搜", "bfs/dfs", "bfs", "dfs", "广度搜索", "深度搜索", "广度优先", "深度优先", "广搜", "深搜"),
    "binary-tree-traversal": ("二叉树遍历", "树遍历", "前序", "中序", "后序", "层序"),
    "binary-tree": ("二叉树",),
    "graph-representation": ("图的表示", "图表示", "邻接矩阵", "邻接表"),
    "shortest-path": ("最短路径",),
}


def resolve_goal_deterministically(goal: str, concepts: list[PlannerConcept]) -> GoalResolution:
    normalized = _normalize(goal)
    full_course = any(marker in normalized for marker in ("完整课程", "全部课程", "整门课程", "系统掌握整门"))
    if full_course:
        target_ids = [item.id for item in concepts]
        intent = _infer_intent(goal, concepts)
        return GoalResolution(course_scope="full_course", target_concept_ids=target_ids[:4], learning_intent=intent, confidence=0.9)
    matched = _explicit_target_ids(goal, concepts)[:4]
    if not matched:
        raise GoalResolutionError()
    return GoalResolution(target_concept_ids=matched, learning_intent=_infer_intent(goal, concepts), confidence=0.75)


def _explicit_target_ids(goal: str, concepts: list[PlannerConcept]) -> list[int]:
    normalized_goal = _normalize(goal)
    matches: list[tuple[PlannerConcept, str]] = []
    for concept in concepts:
        phrases = {
            _normalize(value)
            for value in (concept.name, concept.slug, *_ALIASES.get(concept.slug, ()))
            if _normalize(value)
        }
        matched_phrases = [phrase for phrase in phrases if phrase in normalized_goal]
        if matched_phrases:
            matches.append((concept, max(matched_phrases, key=len)))

    explicit: list[int] = []
    for concept, phrase in matches:
        shadowed_by_more_specific_match = any(
            other.id != concept.id and phrase != other_phrase and phrase in other_phrase
            for other, other_phrase in matches
        )
        if not shadowed_by_more_specific_match:
            explicit.append(concept.id)
    return list(dict.fromkeys(explicit))


def _apply_explicit_target_anchors(
    resolution: GoalResolution,
    goal: str,
    concepts: list[PlannerConcept],
) -> GoalResolution:
    if resolution.course_scope != "focused":
        return resolution
    explicit_ids = _explicit_target_ids(goal, concepts)
    if not explicit_ids:
        return resolution
    return resolution.model_copy(update={"target_concept_ids": explicit_ids[:4]})


def _infer_intent(goal: str, concepts: list[PlannerConcept]) -> LearningIntent:
    normalized = _normalize(goal)
    if any(marker in normalized for marker in ("从零", "零基础")):
        purpose, action, assessment, activities = "concept_learning", "learn", "none", ["explanation", "worked_example", "coding"]
    elif any(marker in normalized for marker in ("小测", "测验", "quiz")):
        purpose, action, assessment, activities = "assessment_preparation", "consolidate", "course_quiz", ["concept_comparison", "worked_example", "error_review", "mock_assessment"]
    elif any(marker in normalized for marker in ("期末", "考试")):
        purpose, action, assessment, activities = "assessment_preparation", "rapid_review", "final_exam", ["explanation", "error_review", "mock_assessment"]
    elif any(marker in normalized for marker in ("面试", "interview")):
        purpose, action, assessment, activities = "interview_preparation", "practice", "interview", ["concept_comparison", "coding"]
    elif any(marker in normalized for marker in ("代码", "实现", "python", "项目")):
        purpose, action, assessment, activities = "project_application", "practice", "none", ["worked_example", "coding"]
    elif any(marker in normalized for marker in ("巩固", "复习")):
        purpose, action, assessment, activities = "skill_consolidation", "consolidate", "none", ["explanation", "worked_example", "error_review"]
    else:
        purpose, action, assessment, activities = "concept_learning", "learn", "none", ["explanation", "worked_example"]
    return LearningIntent(purpose=purpose, action=action, assessment_type=assessment, time_horizon="short_term", preferred_activities=activities, desired_outcome=f"完成目标：{goal[:180]}")


def _resolution_for_context(concepts: list[PlannerConcept], context: PlannerContext) -> GoalResolution:
    if context.preserve_candidate_set and context.persisted_learning_intent and context.persisted_target_concept_ids:
        return GoalResolution(target_concept_ids=context.persisted_target_concept_ids, learning_intent=context.persisted_learning_intent, confidence=1)
    resolution = resolve_goal_deterministically(context.goal, concepts)
    if resolution.course_scope == "full_course":
        return resolution.model_copy(update={"target_concept_ids": [item.id for item in concepts]})
    return resolution


def select_minimal_path(concepts: list[PlannerConcept], relations: list[PlannerRelation], target_concept_ids: list[int], optional_support_concept_ids: list[int], context: PlannerContext, learning_intent: LearningIntent) -> list[SelectedPlannerConcept]:
    concept_by_id = {item.id: item for item in concepts}
    unknown = [item for item in target_concept_ids if item not in concept_by_id]
    if not target_concept_ids or unknown:
        raise GoalResolutionError("目标知识点不存在于当前课程，请改写为课程内的具体知识点。")
    target_ids = set(target_concept_ids)
    selected_ids = set(target_ids)
    hard_incoming: dict[int, list[int]] = {}
    for relation in relations:
        if relation.relation_type == "prerequisite":
            hard_incoming.setdefault(relation.target_concept_id, []).append(relation.source_concept_id)

    visiting: set[int] = set()
    def add_prerequisites(concept_id: int) -> None:
        if concept_id in visiting:
            raise ValueError("Knowledge graph contains a prerequisite cycle.")
        visiting.add(concept_id)
        for prerequisite_id in hard_incoming.get(concept_id, []):
            if context.mastery_scores.get(prerequisite_id, _default_mastery(context.foundation_level)) >= 0.8:
                continue
            add_prerequisites(prerequisite_id)
            selected_ids.add(prerequisite_id)
        visiting.remove(concept_id)
    for target_id in target_ids:
        add_prerequisites(target_id)

    related_pairs = {(item.source_concept_id, item.target_concept_id) for item in relations if item.relation_type == "related"}
    target_chapters = {concept_by_id[item].chapter for item in target_ids}
    for support_id in optional_support_concept_ids[:2]:
        if support_id not in concept_by_id or support_id in selected_ids:
            continue
        weak_same_domain = (
            concept_by_id[support_id].chapter in target_chapters
            and any(_normalize(weak) in _normalize(concept_by_id[support_id].name) or _normalize(concept_by_id[support_id].name) in _normalize(weak) for weak in context.weak_points)
        )
        if weak_same_domain or any((support_id, target) in related_pairs or (target, support_id) in related_pairs for target in target_ids):
            selected_ids.add(support_id)
    if len(selected_ids) > FOCUSED_PATH_MAX_NODES and len(target_ids) <= 4:
        raise GoalResolutionError("目标所需的硬先修链超过 8 个节点，请缩小学习目标后重试。")
    scoped = [concept_by_id[item] for item in selected_ids]
    ordered = _topological_order(scoped, [item for item in relations if item.relation_type == "prerequisite"], context)
    return [SelectedPlannerConcept(item, "target" if item.id in target_ids else "prerequisite") for item in ordered if item.id not in context.completed_concept_ids]


def _topological_order(concepts: list[PlannerConcept], relations: list[PlannerRelation], context: PlannerContext) -> list[PlannerConcept]:
    by_id = {item.id: item for item in concepts}
    incoming = {item.id: 0 for item in concepts}
    outgoing: dict[int, list[int]] = {item.id: [] for item in concepts}
    for relation in relations:
        if relation.source_concept_id in by_id and relation.target_concept_id in by_id:
            incoming[relation.target_concept_id] += 1
            outgoing[relation.source_concept_id].append(relation.target_concept_id)
    ready = sorted((item for item, count in incoming.items() if count == 0), key=lambda item: item)
    ordered: list[PlannerConcept] = []
    while ready:
        current = ready.pop(0)
        ordered.append(by_id[current])
        for target in outgoing[current]:
            incoming[target] -= 1
            if incoming[target] == 0:
                ready.append(target)
                ready.sort()
    if len(ordered) != len(concepts):
        raise ValueError("Knowledge graph contains a prerequisite cycle.")
    return ordered


def _fallback_activities(selected: list[SelectedPlannerConcept], intent: LearningIntent, context: PlannerContext) -> list[PlannerRecommendation]:
    if intent.purpose == "assessment_preparation" and intent.assessment_type != "none":
        return _assessment_fallback_activities(selected, intent, context)
    preferred = list(intent.preferred_activities)
    recommendations = []
    available = _available_minutes(context.available_time)
    per_node_minutes = (
        max(5, min(20, available // len(selected)))
        if available and selected
        else 20
    )
    for index, item in enumerate(selected, start=1):
        activity = preferred[(index - 1) % len(preferred)]
        resource = _resource_for_activity(activity, context.resource_preference)
        recommendations.append(PlannerRecommendation(
            concept_id=item.concept.id, node_role=item.node_role, activity_type=activity,
            objective=f"通过{_activity_label(activity)}掌握“{item.concept.name}”。",
            estimated_minutes=per_node_minutes if item.node_role == "target" else max(5, per_node_minutes - 5),
            success_criterion=f"能够独立说明“{item.concept.name}”并完成一项对应练习。",
            recommended_resource_type=resource,
            reason=f"依据本次学习意图安排{_activity_label(activity)}，且不扩展既定知识点范围。",
            priority=index,
        ))
    return recommendations


def _assessment_fallback_activities(
    selected: list[SelectedPlannerConcept],
    intent: LearningIntent,
    context: PlannerContext,
) -> list[PlannerRecommendation]:
    available = _available_minutes(context.available_time) or 60
    target_count = sum(item.node_role == "target" for item in selected)
    prerequisite_count = len(selected) - target_count
    milestone_minutes = _assessment_minutes(available)
    prerequisite_minutes = 5
    remaining_for_targets = max(
        target_count * 5,
        available - milestone_minutes - prerequisite_count * prerequisite_minutes,
    )
    target_minutes = max(5, remaining_for_targets // max(1, target_count))
    recommendations: list[PlannerRecommendation] = []
    for index, item in enumerate(selected, start=1):
        concept = item.concept
        if item.node_role == "prerequisite":
            recommendations.append(PlannerRecommendation(
                concept_id=concept.id,
                node_role="prerequisite",
                activity_type="worked_example",
                objective=f"用一道诊断题快速确认“{concept.name}”的必要基础，正确后直接进入重点复习。",
                estimated_minutes=prerequisite_minutes,
                success_criterion=f"在 {prerequisite_minutes} 分钟内正确完成“{concept.name}”基础诊断题。",
                recommended_resource_type="practice_questions",
                reason="该节点只用于检查硬先修是否满足，不占用主要复习时间。",
                priority=index,
            ))
            continue
        coverage = concept.description or concept.name
        recommendations.append(PlannerRecommendation(
            concept_id=concept.id,
            node_role="target",
            activity_type="error_review",
            objective=(
                f"围绕“{concept.name}”完成概念对比、典型题和易错点复盘，"
                f"重点覆盖：{coverage}"
            ),
            estimated_minutes=target_minutes,
            success_criterion=f"完成至少 2 道“{concept.name}”典型题，并能解释错误选项或错误步骤。",
            recommended_resource_type="practice_questions",
            reason=f"“{concept.name}”是本次小测准备的明确重点，优先分配练习和复盘时间。",
            priority=index,
        ))
    return recommendations


def _build_path_milestones(
    intent: LearningIntent,
    target_concept_ids: list[int],
    context: PlannerContext,
) -> list[PlannerMilestone]:
    if intent.purpose != "assessment_preparation" or intent.assessment_type == "none":
        return []
    available = _available_minutes(context.available_time) or 60
    assessment_label = {
        "course_quiz": "课程小测",
        "final_exam": "期末考试",
        "interview": "面试检验",
    }.get(intent.assessment_type, "学习检测")
    return [PlannerMilestone(
        milestone_type="mock_assessment",
        title=f"{assessment_label}模拟检验",
        objective="完成一组覆盖全部目标知识点的综合题，并根据错题定位下一轮复习重点。",
        covered_concept_ids=list(dict.fromkeys(target_concept_ids)),
        estimated_minutes=_assessment_minutes(available),
        success_criterion="正确率达到 80%，并能解释每一道错题对应的知识点。",
    )]


def _assessment_minutes(available: int) -> int:
    return max(10, min(20, round(available * 0.25)))


def _rebalance_assessment_minutes(
    output: ActivityOutput,
    selected: list[SelectedPlannerConcept],
    intent: LearningIntent,
    context: PlannerContext,
    reserved_minutes: int = 0,
) -> tuple[ActivityOutput, list[str]]:
    """Keep LLM-authored activities while enforcing assessment time focus."""
    if intent.purpose != "assessment_preparation" or intent.assessment_type == "none":
        return output, []

    roles = {item.concept.id: item.node_role for item in selected}
    ordered = sorted(output.activities, key=lambda item: item.priority)
    prerequisite_ids = [item.concept_id for item in ordered if roles.get(item.concept_id) == "prerequisite"]
    target_ids = [item.concept_id for item in ordered if roles.get(item.concept_id) == "target"]
    if not target_ids:
        return output, []

    available = _available_minutes(context.available_time) or 60
    prerequisite_minutes = 5
    target_budget = max(
        len(target_ids) * 5,
        available - reserved_minutes - len(prerequisite_ids) * prerequisite_minutes,
    )
    target_base, target_remainder = divmod(target_budget, len(target_ids))
    target_position = {concept_id: index for index, concept_id in enumerate(target_ids)}

    changed = False
    rebalanced = []
    for item in output.activities:
        role = roles.get(item.concept_id)
        if role == "prerequisite":
            minutes = prerequisite_minutes
        elif role == "target":
            minutes = target_base + (1 if target_position[item.concept_id] < target_remainder else 0)
        else:
            minutes = item.estimated_minutes
        minutes = max(5, min(60, minutes))
        changed = changed or minutes != item.estimated_minutes
        rebalanced.append(item.model_copy(update={"estimated_minutes": minutes}))

    warnings = ["assessment_time_rebalanced"] if changed else []
    return ActivityOutput(activities=rebalanced), warnings


def _validate_and_convert_activities(
    output: ActivityOutput,
    selected: list[SelectedPlannerConcept],
    context: PlannerContext,
    intent: LearningIntent,
    reserved_minutes: int = 0,
) -> list[PlannerRecommendation]:
    expected = {item.concept.id: item for item in selected}
    if len(output.activities) != len(expected) or {item.concept_id for item in output.activities} != set(expected):
        raise ValueError("Activity output must contain every selected concept exactly once.")
    ordered = sorted(output.activities, key=lambda item: item.priority)
    if [item.priority for item in ordered] != list(range(1, len(ordered) + 1)):
        raise ValueError("Activity priorities must be continuous.")
    for item in ordered:
        if item.node_role != expected[item.concept_id].node_role:
            raise ValueError("Activity node_role must match the validated path role.")
    if intent.purpose == "assessment_preparation" and intent.assessment_type != "none":
        if any(item.node_role == "prerequisite" and item.activity_type == "mock_assessment" for item in ordered):
            raise ValueError("Prerequisite nodes may not consume the path-level mock assessment.")
        target_minutes = sum(item.estimated_minutes for item in ordered if item.node_role == "target")
        prerequisite_minutes = sum(item.estimated_minutes for item in ordered if item.node_role == "prerequisite")
        if prerequisite_minutes and target_minutes < prerequisite_minutes * 2:
            raise ValueError("Assessment preparation must prioritize target concepts over prerequisites.")
    available = _available_minutes(context.available_time)
    if available and sum(item.estimated_minutes for item in ordered) + reserved_minutes > available * 1.2:
        raise ValueError("Activity time clearly exceeds the student's available time.")
    return [PlannerRecommendation(**item.model_dump()) for item in ordered]


def _validate_resolution(resolution: GoalResolution, concepts: list[PlannerConcept], goal: str) -> None:
    known = {item.id for item in concepts}
    if resolution.confidence < 0.65 or any(item not in known for item in resolution.target_concept_ids + resolution.optional_support_concept_ids):
        raise ValueError("Goal resolution confidence or concept IDs are invalid.")
    if resolution.course_scope == "focused" and len(resolution.target_concept_ids) > 4:
        raise ValueError("Focused goal resolution may contain at most four target concepts.")
    if resolution.course_scope == "full_course" and not any(marker in _normalize(goal) for marker in ("完整课程", "全部课程", "整门课程", "系统掌握整门")):
        raise ValueError("Full-course scope was not explicitly requested.")


def _goal_resolution_messages(concepts: list[PlannerConcept], context: PlannerContext) -> list[dict[str, str]]:
    catalog = [{"id": item.id, "name": item.name, "slug": item.slug, "description": item.description, "chapter": item.chapter} for item in concepts]
    profile = {"foundation_level": context.foundation_level, "learning_preference": context.learning_preference, "available_time": context.available_time, "weak_points": context.weak_points, "resource_preference": context.resource_preference, "learning_goal": context.learning_goal, "mastery": context.mastery_scores, "recent_errors": context.recent_errors, "completed_concept_ids": sorted(context.completed_concept_ids)}
    return [{"role": "system", "content": "解析本次学习目标并只返回单个扁平 JSON 对象，不要解释。字段名必须严格使用 course_scope、target_concept_ids、optional_support_concept_ids、purpose、action、assessment_type、time_horizon、preferred_activities、desired_outcome、confidence。格式示例：{\"course_scope\":\"focused\",\"target_concept_ids\":[4],\"optional_support_concept_ids\":[2],\"purpose\":\"assessment_preparation\",\"action\":\"consolidate\",\"assessment_type\":\"course_quiz\",\"time_horizon\":\"short_term\",\"preferred_activities\":[\"concept_comparison\",\"mock_assessment\"],\"desired_outcome\":\"能够区分两种算法\",\"confidence\":0.9}。只选择真实课程 ID；focused 最多 4 个目标和 2 个支持节点。只有用户明确要求完整课程时才用 full_course。画像弱点不得注入目标领域外知识点。"}, {"role": "user", "content": f"用户目标：{context.goal}\n六维画像与学习记录：{json.dumps(profile, ensure_ascii=False)}\n课程概念：{json.dumps(catalog, ensure_ascii=False)}"}]


def _activity_messages(selected: list[SelectedPlannerConcept], intent: LearningIntent, context: PlannerContext) -> list[dict[str, str]]:
    nodes = [{"concept_id": item.concept.id, "name": item.concept.name, "node_role": item.node_role} for item in selected]
    return [{"role": "system", "content": "为既定节点生成简体中文学习活动，只返回一个 JSON 对象，不要解释。根字段必须是 activities。每项必须完整包含 concept_id、node_role、activity_type、objective、estimated_minutes、success_criterion、recommended_resource_type、reason、priority。activity_type 只能是 explanation、concept_comparison、worked_example、coding、error_review、mock_assessment、visual_map；recommended_resource_type 才能使用 guided_note、practice_questions、mind_map、extended_reading、coding_case，禁止混用这两个字段。格式示例：{\"activities\":[{\"concept_id\":4,\"node_role\":\"target\",\"activity_type\":\"concept_comparison\",\"objective\":\"比较 BFS 与 DFS\",\"estimated_minutes\":20,\"success_criterion\":\"能够独立说出三项差异\",\"recommended_resource_type\":\"practice_questions\",\"reason\":\"匹配小测准备目标\",\"priority\":1}]}。每个节点恰好一次，priority 连续，单项 5-60 分钟，不得增加知识点。若目标是测验准备，先修节点不得使用 mock_assessment，目标节点的总时间至少应为先修节点总时间的两倍；最终模拟测验由系统作为路径里程碑另行添加，不要在节点中重复生成。"}, {"role": "user", "content": f"learning_intent：{intent.model_dump_json()}\n可用时间：{context.available_time}\n学习偏好：{context.learning_preference}\n资源偏好：{context.resource_preference}\n节点：{json.dumps(nodes, ensure_ascii=False)}"}]


def _resource_for_activity(activity: str, preference: str) -> str:
    if activity == "coding": return "coding_case"
    if activity in {"error_review", "mock_assessment", "worked_example"}: return "practice_questions"
    if activity == "visual_map": return "mind_map"
    if "代码" in preference or "实操" in preference: return "coding_case"
    if "练习" in preference or "题" in preference: return "practice_questions"
    if "思维" in preference or "图" in preference: return "mind_map"
    if "拓展" in preference: return "extended_reading"
    return "guided_note"


def _activity_label(activity: str) -> str:
    return {"explanation": "概念讲解", "concept_comparison": "概念对比", "worked_example": "典型例题", "coding": "代码实践", "error_review": "易错点复盘", "mock_assessment": "模拟测验", "visual_map": "思维导图"}.get(activity, "学习活动")


def _default_mastery(level: str) -> float:
    normalized = level.casefold()
    if "advanced" in normalized or "进阶" in normalized: return 0.8
    if "practice" in normalized or "实践" in normalized: return 0.7
    if "intermediate" in normalized or "中" in normalized: return 0.6
    return 0.3


def _available_minutes(value: str) -> int | None:
    normalized = value.casefold()
    match = re.search(r"(\d+(?:\.\d+)?)\s*(小时|h|hour)", normalized)
    if match:
        return round(float(match.group(1)) * 60)
    match = re.search(r"(\d+)\s*(分钟|min)", normalized)
    if match:
        return int(match.group(1))
    chinese_hours = {"半": 0.5, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8}
    for number, hours in chinese_hours.items():
        if f"{number}小时" in normalized:
            return round(hours * 60)
    return None


def _normalize(value: str) -> str:
    return re.sub(r"[\s，。、“”‘’：:；;（）()/_-]+", "", value.casefold())


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
    raise ValueError("Planner response did not contain a JSON object.")


def _parse_goal_resolution(content: str) -> GoalResolution:
    payload = json.loads(_extract_json_object(content))
    if isinstance(payload, dict) and "learning_intent" in payload:
        return GoalResolution.model_validate(payload)
    wire = GoalResolutionWire.model_validate(payload)
    return GoalResolution(
        course_scope=wire.course_scope,
        target_concept_ids=wire.target_concept_ids,
        optional_support_concept_ids=wire.optional_support_concept_ids,
        learning_intent=LearningIntent(
            purpose=wire.purpose,
            action=wire.action,
            assessment_type=wire.assessment_type,
            time_horizon=wire.time_horizon,
            preferred_activities=wire.preferred_activities,
            desired_outcome=wire.desired_outcome,
        ),
        confidence=wire.confidence,
    )


def _parse_activity_output(content: str) -> tuple[ActivityOutput, list[str]]:
    payload = json.loads(_extract_json_object(content))
    if isinstance(payload, dict) and "activities" not in payload:
        for alias in ("node", "nodes"):
            if isinstance(payload.get(alias), list):
                payload = {"activities": payload[alias]}
                break
    warnings: list[str] = []
    resource_to_activity = {
        "guided_note": "explanation",
        "practice_questions": "worked_example",
        "mind_map": "visual_map",
        "extended_reading": "explanation",
        "coding_case": "coding",
    }
    if isinstance(payload, dict) and isinstance(payload.get("activities"), list):
        for item in payload["activities"]:
            if not isinstance(item, dict):
                continue
            activity_type = item.get("activity_type")
            if activity_type in resource_to_activity:
                item["activity_type"] = resource_to_activity[activity_type]
                warnings.append("activity_type_repaired")
    return ActivityOutput.model_validate(payload), list(dict.fromkeys(warnings))


def _fallback_reason(exc: Exception) -> str:
    if isinstance(exc, LLMProviderError): return str(exc)
    return f"{type(exc).__name__}: {str(exc)[:240]}" if str(exc) else type(exc).__name__


def _elapsed_ms(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1000))
