from sqlalchemy import select

from app.agents.planner_agents import (
    LearningIntent,
    PlannerConcept,
    PlannerContext,
    PlannerRelation,
    PlannerResult,
    build_planner_agent,
)
from app.db.session import session_scope
from app.db.schema_compat import ensure_learning_path_columns
from app.domain.exceptions import ConflictError, GoalResolutionError, NotFoundError
from app.models import (
    Concept,
    ConceptRelation,
    Course,
    Attempt,
    LearningPath,
    LearningPathItem,
    LearningPathRecommendation,
    MasteryRecord,
    StudentProfile,
)
from app.schemas import LearningPathItemResponse, LearningPathResponse
from app.services.demo_data_service import DEMO_CONCEPT_SLUGS, DemoDataService
from app.services.agent_execution_metadata import build_execution_metadata
from app.services.profile_updater_service import ProfileUpdaterService


class LearningPathService:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url

    def validate_inputs(self, profile_id: int, course_id: int) -> None:
        DemoDataService(database_url=self.database_url).load_demo_data()
        with session_scope(self.database_url) as session:
            self._get_profile_and_course(session, profile_id, course_id)

    def create_path(self, profile_id: int, course_id: int, goal: str) -> LearningPathResponse:
        DemoDataService(database_url=self.database_url).load_demo_data()
        ensure_learning_path_columns(self.database_url)
        with session_scope(self.database_url) as session:
            profile, course = self._get_profile_and_course(session, profile_id, course_id)
            concepts, relations = self._course_graph(session, course.id)
            context = self._planner_context(session, profile, goal)
            result = build_planner_agent().plan(concepts, relations, context)
            concept_by_id = {concept.id: concept for concept in concepts}
            path = LearningPath(
                student_profile_id=profile.id,
                course_id=course.id,
                goal=goal,
                rationale=self._path_rationale(profile, course, goal, result, "initial_creation"),
                status="active",
                learning_intent=result.learning_intent.model_dump() if result.learning_intent else {},
                target_concept_ids=result.target_concept_ids,
                intent_confidence=result.intent_confidence,
                milestones=[item.model_dump() for item in result.milestones],
            )
            session.add(path)
            session.flush()

            items: list[LearningPathItem] = []
            recommendations: list[LearningPathRecommendation] = []
            for index, recommendation in enumerate(result.recommendations, start=1):
                concept = concept_by_id[recommendation.concept_id]
                item = LearningPathItem(
                    path_id=path.id,
                    concept_id=concept.id,
                    order_index=index,
                    title=f"阶段 {index}: {concept.name}",
                    objective=recommendation.objective,
                    rationale=recommendation.reason,
                    status="pending" if index > 1 else "in_progress",
                    node_role=recommendation.node_role,
                    activity_type=recommendation.activity_type,
                    estimated_minutes=recommendation.estimated_minutes,
                    success_criterion=recommendation.success_criterion,
                )
                session.add(item)
                session.flush()
                items.append(item)
                record = self._recommendation_record(item.id, recommendation, result)
                session.add(record)
                recommendations.append(record)
            session.flush()
            return self._to_path_response(path, items, recommendations, result)

    @staticmethod
    def _get_profile_and_course(session, profile_id: int, course_id: int) -> tuple[StudentProfile, Course]:
        profile = session.get(StudentProfile, profile_id)
        if profile is None:
            raise NotFoundError("Student profile", profile_id)
        course = session.get(Course, course_id)
        if course is None:
            raise NotFoundError("Course", course_id)
        return profile, course

    def get_path(self, path_id: int) -> LearningPathResponse:
        with session_scope(self.database_url) as session:
            path = session.get(LearningPath, path_id)
            if path is None:
                raise NotFoundError("Learning path", path_id)
            items = self._path_items(session, path.id)
            recommendations = self._recommendations(session, items)
            return self._to_path_response(path, items, recommendations)

    def complete_item(self, item_id: int) -> LearningPathResponse:
        with session_scope(self.database_url) as session:
            item = session.get(LearningPathItem, item_id)
            if item is None:
                raise NotFoundError("Learning path item", item_id)
            if item.status == "completed":
                raise ConflictError(f"Learning path item {item_id} is already completed.")
            path = session.get(LearningPath, item.path_id)
            if path is None:
                raise NotFoundError("Learning path", item.path_id)
            item.status = "completed"
            path_id = path.id
            profile_id = path.student_profile_id
            course_id = path.course_id
            session.flush()
            next_item = session.scalar(
                select(LearningPathItem).where(
                    LearningPathItem.path_id == path.id,
                    LearningPathItem.status != "completed",
                ).order_by(LearningPathItem.order_index).limit(1)
            )
            if next_item is not None:
                next_item.status = "in_progress"
            path.status = "active" if next_item is not None else "completed"
            session.flush()

        ProfileUpdaterService(database_url=self.database_url).update_from_trace(
            profile_id,
            trigger_type="path_item_completed",
            event_key=f"path_item:{item_id}:completed",
        )
        if self.get_path(path_id).status != "completed":
            try:
                self.refresh_active_paths(profile_id, course_id, trigger=f"path_item:{item_id}:completed")
            except GoalResolutionError:
                # Legacy paths may not have persisted intent metadata. Completion remains valid,
                # and the next node has already advanced without requiring a successful replan.
                pass
        return self.get_path(path_id)

    def refresh_active_paths(
        self,
        profile_id: int,
        course_id: int,
        trigger: str,
        path_id: int | None = None,
    ) -> list[LearningPathResponse]:
        refreshed: list[LearningPathResponse] = []
        trace_payloads: list[tuple[int, PlannerResult]] = []
        with session_scope(self.database_url) as session:
            profile, course = self._get_profile_and_course(session, profile_id, course_id)
            concepts, relations = self._course_graph(session, course.id)
            path_query = select(LearningPath).where(
                LearningPath.student_profile_id == profile_id,
                LearningPath.course_id == course_id,
                LearningPath.status == "active",
            )
            if path_id is not None:
                path_query = path_query.where(LearningPath.id == path_id)
            paths = session.scalars(path_query).all()
            for path in paths:
                items = self._path_items(session, path.id)
                completed_items = [item for item in items if item.status == "completed"]
                completed_ids = {item.concept_id for item in completed_items}
                path_concept_ids = {item.concept_id for item in items}
                path_concepts = [concept for concept in concepts if concept.id in path_concept_ids]
                path_relations = [
                    relation
                    for relation in relations
                    if relation.source_concept_id in path_concept_ids
                    and relation.target_concept_id in path_concept_ids
                ]
                context = self._planner_context(
                    session,
                    profile,
                    path.goal,
                    completed_ids,
                    preserve_candidate_set=True,
                    persisted_learning_intent=path.learning_intent,
                    persisted_target_concept_ids=path.target_concept_ids,
                )
                result = build_planner_agent().plan(path_concepts, path_relations, context)
                pending_by_concept = {item.concept_id: item for item in items if item.status != "completed"}
                if set(pending_by_concept) != {item.concept_id for item in result.recommendations}:
                    raise ValueError("Planner refresh did not preserve the pending concept set.")

                start_index = len(completed_items) + 1
                recommendation_records = {record.path_item_id: record for record in self._recommendations(session, items)}
                for offset, recommendation in enumerate(result.recommendations):
                    item = pending_by_concept[recommendation.concept_id]
                    item.order_index = start_index + offset
                    item.title = f"阶段 {item.order_index}: {self._concept_name(concepts, item.concept_id)}"
                    item.rationale = recommendation.reason
                    item.objective = recommendation.objective
                    item.node_role = recommendation.node_role
                    item.activity_type = recommendation.activity_type
                    item.estimated_minutes = recommendation.estimated_minutes
                    item.success_criterion = recommendation.success_criterion
                    item.status = "in_progress" if offset == 0 else "pending"
                    record = recommendation_records.get(item.id)
                    if record is None:
                        record = self._recommendation_record(item.id, recommendation, result)
                        session.add(record)
                        recommendation_records[item.id] = record
                    else:
                        self._update_recommendation_record(record, recommendation, result)
                path.rationale = self._path_rationale(profile, course, path.goal, result, trigger)
                path.milestones = [item.model_dump() for item in result.milestones]
                session.flush()
                ordered_items = self._path_items(session, path.id)
                records = self._recommendations(session, ordered_items)
                refreshed.append(self._to_path_response(path, ordered_items, records, result))
                trace_payloads.append((path.id, result))

        for path_id, result in trace_payloads:
            self._record_replan_trace(profile_id, course_id, path_id, trigger, result)
        return refreshed

    def _course_graph(self, session, course_id: int) -> tuple[list[PlannerConcept], list[PlannerRelation]]:
        course = session.get(Course, course_id)
        concept_query = select(Concept).where(Concept.course_id == course_id)
        if course is not None and course.is_demo:
            concept_query = concept_query.where(Concept.slug.in_(DEMO_CONCEPT_SLUGS))
        concept_rows = session.scalars(concept_query).all()
        concepts = [
            PlannerConcept(
                id=concept.id,
                slug=concept.slug,
                name=concept.name,
                chapter=concept.chapter or "数据结构",
                difficulty=concept.difficulty,
                description=concept.description or "",
            )
            for concept in concept_rows
        ]
        concept_ids = {concept.id for concept in concepts}
        relation_rows = session.scalars(select(ConceptRelation)).all()
        relations = [
            PlannerRelation(row.source_concept_id, row.target_concept_id, row.relation_type)
            for row in relation_rows
            if row.source_concept_id in concept_ids and row.target_concept_id in concept_ids
        ]
        return concepts, relations

    def _planner_context(
        self,
        session,
        profile: StudentProfile,
        goal: str,
        completed_ids: set[int] | None = None,
        preserve_candidate_set: bool = False,
        persisted_learning_intent: dict | None = None,
        persisted_target_concept_ids: list[int] | None = None,
    ) -> PlannerContext:
        preferences = profile.preferences if isinstance(profile.preferences, dict) else {}
        mastery: dict[int, float] = {}
        records = session.scalars(
            select(MasteryRecord)
            .where(MasteryRecord.student_profile_id == profile.id)
            .order_by(MasteryRecord.id)
        ).all()
        for record in records:
            mastery[record.concept_id] = record.mastery_score
        recent_attempts = session.scalars(
            select(Attempt)
            .where(Attempt.student_profile_id == profile.id, Attempt.score < 0.8)
            .order_by(Attempt.id.desc())
            .limit(5)
        ).all()
        weak_points = [
            item.strip()
            for item in str(preferences.get("weak_points") or "").replace("，", "、").split("、")
            if item.strip()
        ]
        return PlannerContext(
            goal=goal,
            profile_type=str(profile.profile_type),
            foundation_level=str(preferences.get("foundation_level") or profile.level),
            learning_preference=str(preferences.get("learning_preference") or preferences.get("style") or "step_by_step"),
            available_time=str(preferences.get("available_time") or profile.time_budget),
            weak_points=weak_points[:5],
            resource_preference=str(preferences.get("resource_preference") or preferences.get("resource") or "讲解文档"),
            completed_concept_ids=completed_ids or set(),
            mastery_scores=mastery,
            preserve_candidate_set=preserve_candidate_set,
            learning_goal=str(profile.goal or ""),
            recent_errors=[attempt.feedback[:240] for attempt in recent_attempts if attempt.feedback],
            persisted_learning_intent=LearningIntent.model_validate(persisted_learning_intent) if persisted_learning_intent else None,
            persisted_target_concept_ids=list(persisted_target_concept_ids or []),
        )

    def _path_items(self, session, path_id: int) -> list[LearningPathItem]:
        return session.scalars(
            select(LearningPathItem)
            .where(LearningPathItem.path_id == path_id)
            .order_by(LearningPathItem.order_index)
        ).all()

    def _recommendations(self, session, items: list[LearningPathItem]) -> list[LearningPathRecommendation]:
        item_ids = [item.id for item in items]
        if not item_ids:
            return []
        return session.scalars(
            select(LearningPathRecommendation).where(LearningPathRecommendation.path_item_id.in_(item_ids))
        ).all()

    def _recommendation_record(self, item_id, recommendation, result: PlannerResult) -> LearningPathRecommendation:
        return LearningPathRecommendation(
            path_item_id=item_id,
            resource_type=recommendation.recommended_resource_type,
            reason=recommendation.reason,
            priority=recommendation.priority,
            execution_mode=result.execution_mode,
            provider=result.provider,
            model=result.model,
            fallback_used=result.fallback_used,
            fallback_reason=result.fallback_reason,
            duration_ms=result.duration_ms,
        )

    def _update_recommendation_record(self, record, recommendation, result: PlannerResult) -> None:
        record.resource_type = recommendation.recommended_resource_type
        record.reason = recommendation.reason
        record.priority = recommendation.priority
        record.execution_mode = result.execution_mode
        record.provider = result.provider
        record.model = result.model
        record.fallback_used = result.fallback_used
        record.fallback_reason = result.fallback_reason
        record.duration_ms = result.duration_ms

    def _to_path_response(
        self,
        path: LearningPath,
        items: list[LearningPathItem],
        recommendations: list[LearningPathRecommendation],
        planner_result: PlannerResult | None = None,
    ) -> LearningPathResponse:
        by_item = {record.path_item_id: record for record in recommendations}
        first_record = next((by_item.get(item.id) for item in items if by_item.get(item.id)), None)
        response_items = []
        for item in items:
            record = by_item.get(item.id)
            response_items.append(
                LearningPathItemResponse(
                    id=item.id,
                    path_id=item.path_id,
                    concept_id=item.concept_id,
                    order_index=item.order_index,
                    title=item.title,
                    objective=item.objective,
                    rationale=item.rationale,
                    status=item.status,
                    recommended_resource_type=record.resource_type if record else None,
                    recommendation_reason=record.reason if record else item.rationale,
                    priority=record.priority if record else item.order_index,
                    node_role=item.node_role,
                    activity_type=item.activity_type,
                    estimated_minutes=item.estimated_minutes,
                    success_criterion=item.success_criterion,
                )
            )
        return LearningPathResponse(
            id=path.id,
            student_profile_id=path.student_profile_id,
            course_id=path.course_id,
            goal=path.goal,
            rationale=path.rationale,
            status=path.status,
            items=response_items,
            created_at=path.created_at,
            execution_mode=first_record.execution_mode if first_record else "rule_based",
            provider=first_record.provider if first_record else "rule_based",
            model=first_record.model if first_record else "",
            fallback_used=first_record.fallback_used if first_record else False,
            fallback_reason=first_record.fallback_reason if first_record else None,
            planner_duration_ms=first_record.duration_ms if first_record else 0,
            provider_duration_ms=int((planner_result.provider_metadata if planner_result else {}).get("provider_duration_ms") or 0),
            retry_count=int((planner_result.provider_metadata if planner_result else {}).get("retry_count") or 0),
            token_usage=dict((planner_result.provider_metadata if planner_result else {}).get("usage") or {}),
            learning_intent=dict(path.learning_intent or {}),
            target_concept_ids=list(path.target_concept_ids or []),
            intent_confidence=float(path.intent_confidence or 0),
            milestones=list(path.milestones or []),
            planner_phases=[{
                "phase": item.phase,
                "execution_mode": item.execution_mode,
                "fallback_reason": item.fallback_reason,
                "warning_reason": item.warning_reason,
            } for item in (planner_result.phase_traces if planner_result else [])],
        )

    def _path_rationale(self, profile, course, goal: str, result: PlannerResult, trigger: str) -> str:
        return (
            f"Planner Agent 使用知识图谱先修约束与画像排序；trigger={trigger}；"
            f"execution_mode={result.execution_mode}；provider={result.provider}；"
            f"warning={result.warning_reason or 'none'}；"
            f"基础水平={profile.level}；课程={course.title}；目标={goal}。"
        )

    def _record_replan_trace(self, profile_id, course_id, path_id, trigger: str, result: PlannerResult) -> None:
        from app.services.agent_run_service import AgentRunService

        run_service = AgentRunService(database_url=self.database_url)
        run = run_service.start_run(
            "learning_path_replanning",
            profile_id,
            course_id,
            input_summary=f"path_id={path_id}; trigger={trigger}",
        )
        run_service.record_step(
            run.id,
            "planner",
            input_summary=f"Recompute pending nodes for path_id={path_id}; trigger={trigger}",
            output_summary=f"Re-ranked {len(result.recommendations)} pending nodes.",
            decision_basis=(
                f"execution_mode={result.execution_mode}; provider={result.provider}; model={result.model or 'none'}; "
                f"fallback_used={str(result.fallback_used).lower()}; fallback_reason={result.fallback_reason or 'none'}; "
                f"warning={result.warning_reason or 'none'}"
            ),
            status="completed",
            duration_ms=result.duration_ms,
            execution_metadata=build_execution_metadata(result),
        )
        run_service.complete_run(run.id, f"Planner refreshed path {path_id} after {trigger}.")

    @staticmethod
    def _concept_name(concepts: list[PlannerConcept], concept_id: int) -> str:
        return next(concept.name for concept in concepts if concept.id == concept_id)
