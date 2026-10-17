from dataclasses import dataclass

from app.agents.router_agent import RuleBasedRouterAgent
from app.domain.exceptions import GoalResolutionError


@dataclass(frozen=True)
class LearningFlowResult:
    agent_run_id: int
    learning_path_id: int
    final_summary: str


class AgentOrchestrator:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url
        self.router_agent = RuleBasedRouterAgent()

    def run_learning_flow(self, profile_id: int, course_id: int, goal: str) -> LearningFlowResult:
        from app.services.agent_run_service import AgentRunService
        from app.services.agent_execution_metadata import build_execution_metadata
        from app.services.learning_path_service import LearningPathService

        run_service = AgentRunService(database_url=self.database_url)
        path_service = LearningPathService(database_url=self.database_url)

        path_service.validate_inputs(profile_id, course_id)
        route = self.router_agent.route_learning_path(goal, profile_id, course_id)
        run = run_service.start_run(
            "learning_path_planning",
            profile_id,
            course_id,
            input_summary=route.to_log_summary(),
        )
        run_service.record_step(
            run.id,
            "router",
            input_summary=f"profile_id={profile_id}; course_id={course_id}; goal={goal}",
            output_summary=route.to_log_summary(),
            decision_basis=f"Router Agent dispatches path planning with constraints: {route.constraints}",
            status="completed",
        )
        try:
            path = path_service.create_path(profile_id, course_id, goal)
        except GoalResolutionError as exc:
            run_service.record_step(
                run.id, "planner", "解析本次学习目标。", "未创建学习路径。",
                "phase=goal_resolution; 目标无法可靠映射到课程知识点。", "failed", error=str(exc),
            )
            run_service.fail_run(run.id, str(exc))
            raise
        phases = path.planner_phases or [{"phase": "activity_generation", "execution_mode": path.execution_mode}]
        for phase in phases:
            run_service.record_step(
                run.id,
                "planner",
                input_summary=f"Planner phase={phase['phase']}；profile_id={profile_id}；course_id={course_id}。",
                output_summary=(f"生成 {len(path.items)} 个学习节点。" if phase["phase"] == "activity_generation" else "完成该阶段校验。"),
                decision_basis=(
                    f"phase={phase['phase']}; execution_mode={phase['execution_mode']}; "
                    f"provider={path.provider}; model={path.model or 'none'}; "
                    f"fallback_reason={phase.get('fallback_reason') or 'none'}; "
                    f"warning_reason={phase.get('warning_reason') or 'none'}"
                ),
                status="completed",
                duration_ms=path.planner_duration_ms if phase["phase"] == "activity_generation" else 0,
                execution_metadata=build_execution_metadata(
                    execution_mode=phase["execution_mode"], provider=path.provider, model=path.model,
                    fallback_used="fallback" in phase["execution_mode"],
                    fallback_reason=phase.get("fallback_reason"),
                    duration_ms=path.planner_duration_ms if phase["phase"] == "activity_generation" else 0,
                ),
            )
        final_summary = f"Planner Agent 已生成学习路径 {path.id}，包含 {len(path.items)} 个步骤。"
        run_service.complete_run(run.id, final_summary)
        return LearningFlowResult(
            agent_run_id=run.id,
            learning_path_id=path.id,
            final_summary=final_summary,
        )
