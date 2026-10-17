from app.agents.router_agent import RuleBasedRouterAgent
from app.agents.tutor_factory import build_tutor_agent
from app.domain.exceptions import NotFoundError
from app.models import Course, StudentProfile
from app.db.session import session_scope
from app.schemas import TutorAskResponse
from app.services.agent_run_service import AgentRunService
from app.services.agent_execution_metadata import build_execution_metadata
from app.services.citation_service import source_ref_summary, validate_citations
from app.services.content_safety_service import ContentSafetyService
from app.services.knowledge_base_service import KnowledgeBaseService
from app.services.profile_postprocessing_service import ProfilePostprocessingService


class TutorService:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url
        self.agent = build_tutor_agent()
        self.router_agent = RuleBasedRouterAgent()

    def ask(self, profile_id: int, course_id: int, question: str) -> TutorAskResponse:
        with session_scope(self.database_url) as session:
            profile = session.get(StudentProfile, profile_id)
            course = session.get(Course, course_id)
            if profile is None:
                raise NotFoundError("Student profile", profile_id)
            if course is None:
                raise NotFoundError("Course", course_id)

        input_safety = ContentSafetyService().review_input(question)
        if not input_safety.allowed:
            run_service = AgentRunService(database_url=self.database_url)
            run = run_service.start_run(
                "tutor_answer",
                profile_id,
                course_id,
                input_summary="Tutor input was evaluated by deterministic content-safety rules.",
            )
            run_service.record_step(
                run.id,
                "evaluator",
                input_summary="Review Tutor input without persisting blocked content.",
                output_summary="安全策略已拦截 Tutor 输入，未执行检索或 LLM 调用。",
                decision_basis=f"category={input_safety.category}; reason={input_safety.reason}",
                status="completed",
            )
            run_service.complete_run(run.id, "Tutor request was safely blocked before retrieval and generation.")
            return TutorAskResponse(
                answer=input_safety.user_message,
                source_refs=[],
                agent_run_id=run.id,
                safety_status="blocked",
                safety_message=input_safety.user_message,
            )

        route = self.router_agent.route_tutor_question(question, profile_id, course_id)
        run_service = AgentRunService(database_url=self.database_url)
        run = run_service.start_run("tutor_answer", profile_id, course_id, input_summary=route.to_log_summary())
        run_service.record_step(
            run.id,
            "router",
            input_summary=f"profile_id={profile_id}; course_id={course_id}; question={question[:160]}",
            output_summary=route.to_log_summary(),
            decision_basis=f"Router Agent dispatches grounded tutor task with constraints: {route.constraints}",
            status="completed",
        )

        retrieved_chunks = KnowledgeBaseService(database_url=self.database_url).search(
            course_id,
            question,
            top_k=5,
            owner_user_id=profile.user_id,
        )
        retrieval_safety = ContentSafetyService().filter_retrieved_chunks(retrieved_chunks)
        chunks = retrieval_safety.safe_chunks
        run_service.record_step(
            run.id,
            "retriever",
            input_summary=f"query={question[:180]}; top_k=5",
            output_summary=(
                f"Retriever Agent returned {len(retrieved_chunks)} chunks; "
                f"{len(chunks)} passed deterministic safety filtering for Tutor Agent."
            ),
            decision_basis="Only Retriever Agent can call KnowledgeBaseService.search before Tutor Agent answers.",
            status="completed",
            execution_metadata=build_execution_metadata(
                source_refs=[chunk.source_ref for chunk in chunks if chunk.source_ref]
            ),
        )
        if retrieval_safety.blocked_source_refs:
            run_service.record_step(
                run.id,
                "evaluator",
                input_summary="Review retrieved chunks as untrusted content.",
                output_summary=f"安全规则隔离了 {len(retrieval_safety.blocked_source_refs)} 个 RAG 污染片段。",
                decision_basis=(
                    "unsafe untrusted content detected in retrieved source refs: "
                    + ",".join(retrieval_safety.blocked_source_refs)
                ),
                status="completed",
                execution_metadata=build_execution_metadata(
                    source_refs=retrieval_safety.blocked_source_refs
                ),
            )
        profile_summary = f"type={profile.profile_type}; level={profile.level}; goal={profile.goal}; time_budget={profile.time_budget}"
        result = self.agent.answer(question, chunks, profile_summary, course.title)
        source_summary = source_ref_summary(result.source_refs)
        citation_check = validate_citations(result.answer, result.source_refs)
        citation_note = _citation_trace_note(citation_check)
        run_service.record_step(
            run.id,
            "tutor",
            result.input_summary,
            f"{result.output_summary} {source_summary}{citation_note}",
            f"{result.decision_basis} {source_summary}{citation_note}",
            "completed",
            execution_metadata=build_execution_metadata(result),
        )
        run_service.complete_run(run.id, f"Tutor Agent 已回答 profile {profile_id} 的问题。")
        postprocessing_task = ProfilePostprocessingService(database_url=self.database_url).schedule(
            profile_id,
            trigger_type="tutor",
            event_key=f"tutor:{run.id}",
        )
        return TutorAskResponse(
            answer=result.answer,
            source_refs=result.source_refs,
            agent_run_id=run.id,
            safety_status="degraded" if result.fallback_used else "passed",
            safety_message=(f"已安全降级：{result.fallback_reason}" if result.fallback_used else "内容已通过引用与安全校验。"),
            postprocessing_task_id=postprocessing_task.id,
            postprocessing_status=postprocessing_task.status,
        )


def _citation_trace_note(citation_check: dict) -> str:
    fake_refs = citation_check.get("fake_source_refs") or []
    if fake_refs:
        return f" Citation warning: fake sources {', '.join(str(ref) for ref in fake_refs)}."
    if citation_check.get("missing_citation"):
        return " Citation warning: answer did not cite retrieved sources inline."
    return ""
