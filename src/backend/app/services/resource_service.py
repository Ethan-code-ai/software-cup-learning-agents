from dataclasses import replace

from sqlalchemy import select

from app.agents.critic_agents import RuleBasedCriticAgent
from app.agents.router_agent import RuleBasedRouterAgent
from app.agents.resource_factory import build_resource_agent
from app.agents.rule_based_agents import RuleBasedResourceAgent
from app.db.session import session_scope
from app.db.schema_compat import ensure_generated_resource_columns
from app.domain.exceptions import NotFoundError
from app.models import Concept, GeneratedResource, LearningPath, LearningPathItem, StudentProfile
from app.schemas import GeneratedResourceResponse
from app.services.agent_run_service import AgentRunService
from app.services.animation_spec_service import AnimationSpecService
from app.services.agent_execution_metadata import build_execution_metadata
from app.services.citation_service import source_ref_summary
from app.services.content_safety_service import ContentSafetyService
from app.services.demo_data_service import DemoDataService
from app.services.knowledge_base_service import KnowledgeBaseService
from app.services.profile_postprocessing_service import ProfilePostprocessingService


class ResourceService:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url
        ensure_generated_resource_columns(database_url)
        self.agent = build_resource_agent()
        self.router_agent = RuleBasedRouterAgent()
        self.critic_agent = RuleBasedCriticAgent()

    def generate_resource(self, path_item_id: int, resource_type: str) -> GeneratedResourceResponse:
        DemoDataService(database_url=self.database_url).get_status()

        with session_scope(self.database_url) as session:
            path_item = session.get(LearningPathItem, path_item_id)
            if path_item is None:
                raise NotFoundError("Learning path item", path_item_id)
            path = session.get(LearningPath, path_item.path_id)
            concept = session.get(Concept, path_item.concept_id)
            if path is None:
                raise NotFoundError("Learning path", path_item.path_id)
            if concept is None:
                raise NotFoundError("Concept", path_item.concept_id)

            path_item_id_value = path_item.id
            objective = path_item.objective
            profile_id = path.student_profile_id
            course_id = path.course_id
            concept_name = concept.name
            concept_slug = concept.slug
            profile = session.get(StudentProfile, profile_id)
            profile_preferences = profile.preferences if profile is not None and isinstance(profile.preferences, dict) else {}
            if profile is not None:
                profile_preferences = {
                    **profile_preferences,
                    "foundation_level": profile.level,
                    "learning_goal": profile.goal,
                    "available_time": profile.time_budget,
                    "profile_type": profile.profile_type,
                }
            owner_user_id = profile.user_id if profile is not None else None

        route = self.router_agent.route_resource_generation(resource_type, concept_name, objective, profile_preferences)
        run_service = AgentRunService(database_url=self.database_url)
        run = run_service.start_run(
            "resource_generation",
            profile_id,
            course_id,
            input_summary=route.to_log_summary(),
        )
        run_service.record_step(
            run.id,
            "router",
            input_summary=f"resource_type={resource_type}; concept={concept_name}; objective={objective}",
            output_summary=route.to_log_summary(),
            decision_basis=f"Router Agent only dispatches JSON-style task constraints: {route.constraints}",
            status="completed",
        )

        resource_query = f"{concept_name} {concept_slug} {objective}"
        retrieved_chunks = KnowledgeBaseService(database_url=self.database_url).search(
            course_id,
            resource_query,
            top_k=5,
            owner_user_id=owner_user_id,
        )
        retrieval_safety = ContentSafetyService().filter_retrieved_chunks(retrieved_chunks)
        chunks = retrieval_safety.safe_chunks
        run_service.record_step(
            run.id,
            "retriever",
            input_summary=f"query={resource_query}; top_k=5",
            output_summary=(
                f"Retriever Agent returned {len(retrieved_chunks)} chunks; "
                f"{len(chunks)} passed deterministic safety filtering for Resource Agent."
            ),
            decision_basis="Only Retriever Agent can call KnowledgeBaseService.search and expose source_refs.",
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
                execution_metadata=build_execution_metadata(source_refs=retrieval_safety.blocked_source_refs),
            )
        result = self.agent.generate(concept_name, objective, resource_type, chunks, profile_preferences)
        animation_spec = AnimationSpecService().build(
            concept_name=concept_name,
            concept_slug=concept_slug,
            objective=objective,
            resource_type=resource_type,
        )
        available_source_refs = {str(chunk.source_ref) for chunk in chunks if chunk.source_ref}
        run_service.record_step(
            run.id,
            "resource",
            result.input_summary,
            f"{result.output_summary} {source_ref_summary(result.source_refs)}",
            f"{result.decision_basis} {source_ref_summary(result.source_refs)}",
            "completed",
            execution_metadata=build_execution_metadata(result),
        )
        critic = self.critic_agent.review_resource(result, resource_type, profile_preferences, available_source_refs)
        run_service.record_step(
            run.id,
            "evaluator",
            input_summary=f"review resource_type={resource_type}; source_refs={len(result.source_refs)}",
            output_summary=critic.output_summary,
            decision_basis=critic.decision_basis,
            status="completed" if critic.approved else "failed",
        )
        if not critic.approved:
            revised_objective = f"{objective}\nCritic revision: {critic.revision_instruction}"
            result = self.agent.generate(concept_name, revised_objective, resource_type, chunks, profile_preferences)
            run_service.record_step(
                run.id,
                "resource",
                result.input_summary,
                f"Resource Agent regenerated after Critic feedback. {result.output_summary} {source_ref_summary(result.source_refs)}",
                f"Revision instruction: {critic.revision_instruction}. {result.decision_basis}",
                "completed",
                execution_metadata=build_execution_metadata(result),
            )
            second_critic = self.critic_agent.review_resource(
                result, resource_type, profile_preferences, available_source_refs
            )
            run_service.record_step(
                run.id,
                "evaluator",
                input_summary="review regenerated resource",
                output_summary=second_critic.output_summary,
                decision_basis=second_critic.decision_basis,
                status="completed" if second_critic.approved else "failed",
            )
            if not second_critic.approved:
                rejected_result = result
                fallback_reason = f"Critic rejected regenerated resource: {second_critic.output_summary}"
                result = replace(
                    RuleBasedResourceAgent().generate(
                        concept_name, objective, resource_type, chunks, profile_preferences
                    ),
                    execution_mode="rule_based_fallback",
                    provider=rejected_result.provider,
                    model=rejected_result.model,
                    fallback_used=True,
                    fallback_reason=fallback_reason,
                    duration_ms=rejected_result.duration_ms,
                    output_summary="Critic 连续拒绝生成资源，已使用 rule-based safety fallback。",
                    decision_basis=(
                        f"execution_mode=rule_based_fallback; provider={rejected_result.provider}; "
                        f"model={rejected_result.model or 'none'}; fallback_used=true; "
                        f"fallback_reason={fallback_reason}"
                    ),
                )
                run_service.record_step(
                    run.id,
                    "resource",
                    result.input_summary,
                    result.output_summary,
                    result.decision_basis,
                    "completed",
                    execution_metadata=build_execution_metadata(result),
                )
                final_critic = self.critic_agent.review_resource(
                    result, resource_type, profile_preferences, available_source_refs
                )
                run_service.record_step(
                    run.id,
                    "evaluator",
                    input_summary="review rule-based safety fallback resource",
                    output_summary=final_critic.output_summary,
                    decision_basis=final_critic.decision_basis,
                    status="completed" if final_critic.approved else "failed",
                )
                if not final_critic.approved:
                    raise ValueError(f"Resource safety fallback failed Critic review: {final_critic.output_summary}")

        with session_scope(self.database_url) as session:
            resource = GeneratedResource(
                path_item_id=path_item_id_value,
                resource_type=resource_type,
                content=result.content,
                source_refs=result.source_refs,
                animation_spec=animation_spec.model_dump() if animation_spec is not None else None,
            )
            session.add(resource)
            session.flush()
            response = GeneratedResourceResponse.model_validate(resource)

        run_service.complete_run(run.id, f"Multi-agent resource flow generated resource {response.id} for path_item {path_item_id_value}.")
        postprocessing_task = ProfilePostprocessingService(database_url=self.database_url).schedule(
            profile_id,
            trigger_type="resource",
            event_key=f"resource:{run.id}",
        )
        response.agent_run_id = run.id
        response.postprocessing_task_id = postprocessing_task.id
        response.postprocessing_status = postprocessing_task.status
        response.safety_status = "degraded" if result.fallback_used or not chunks else "passed"
        response.safety_message = (
            "课程资料不足，已停止事实性资源生成。"
            if not chunks
            else (f"已安全降级：{result.fallback_reason}" if result.fallback_used else "内容已通过引用与安全校验。")
        )
        return response

    def list_resources_for_path_item(self, path_item_id: int) -> list[GeneratedResourceResponse]:
        with session_scope(self.database_url) as session:
            resources = session.scalars(
                select(GeneratedResource).where(GeneratedResource.path_item_id == path_item_id).order_by(GeneratedResource.id)
            ).all()
            return [GeneratedResourceResponse.model_validate(resource) for resource in resources]
