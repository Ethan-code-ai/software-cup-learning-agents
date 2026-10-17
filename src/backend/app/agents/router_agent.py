from dataclasses import dataclass, field
from typing import Any


AGENT_TOOL_POLICY: dict[str, tuple[str, ...]] = {
    "router": ("intent_classification", "task_dispatch_json"),
    "retriever": ("knowledge_search", "source_ref_extraction"),
    "profile_updater": ("profile_read", "profile_write", "agent_trace_read"),
    "resource": ("resource_generation", "markdown_formatting"),
    "quiz": ("quiz_generation", "difficulty_control"),
    "tutor": ("grounded_answering", "citation_validation"),
    "evaluator": ("rubric_scoring", "critic_review", "mastery_update"),
}


@dataclass(frozen=True)
class RouterDecision:
    intent: str
    target_agent: str
    support_agents: list[str]
    required_tools: list[str]
    constraints: dict[str, Any] = field(default_factory=dict)

    def to_log_summary(self) -> str:
        supports = ",".join(self.support_agents) if self.support_agents else "none"
        tools = ",".join(self.required_tools)
        return f"intent={self.intent}; target={self.target_agent}; support={supports}; tools={tools}"


class RuleBasedRouterAgent:
    def route_learning_path(self, goal: str, profile_id: int, course_id: int) -> RouterDecision:
        return RouterDecision(
            intent="plan_learning_path",
            target_agent="planner",
            support_agents=["profile_updater", "evaluator"],
            required_tools=["profile_read", "concept_graph_read", "path_planning", "mastery_read"],
            constraints={
                "goal": goal,
                "profile_id": profile_id,
                "course_id": course_id,
                "adaptive_ordering": True,
            },
        )

    def route_resource_generation(
        self,
        resource_type: str,
        concept_name: str,
        objective: str,
        profile_preferences: dict[str, Any] | None = None,
    ) -> RouterDecision:
        preferences = profile_preferences or {}
        return RouterDecision(
            intent="generate_learning_resource",
            target_agent="resource",
            support_agents=["retriever", "profile_updater", "evaluator"],
            required_tools=[
                *AGENT_TOOL_POLICY["retriever"],
                *AGENT_TOOL_POLICY["resource"],
                *AGENT_TOOL_POLICY["evaluator"],
            ],
            constraints={
                "resource_type": resource_type,
                "concept_name": concept_name,
                "objective": objective,
                "foundation_level": preferences.get("foundation_level") or preferences.get("level"),
                "weak_points": preferences.get("weak_points"),
                "grounding_required": True,
                "critic_required": True,
            },
        )

    def route_quiz_generation(
        self,
        difficulty: str,
        concept_name: str,
        profile_preferences: dict[str, Any] | None = None,
    ) -> RouterDecision:
        preferences = profile_preferences or {}
        foundation = str(preferences.get("foundation_level") or preferences.get("level") or "").lower()
        adjusted_difficulty = "easy" if any(term in foundation for term in ("weak", "薄弱", "基础")) else difficulty
        return RouterDecision(
            intent="generate_adaptive_quiz",
            target_agent="quiz",
            support_agents=["retriever", "evaluator"],
            required_tools=[
                *AGENT_TOOL_POLICY["retriever"],
                *AGENT_TOOL_POLICY["quiz"],
                *AGENT_TOOL_POLICY["evaluator"],
            ],
            constraints={
                "concept_name": concept_name,
                "requested_difficulty": difficulty,
                "effective_difficulty": adjusted_difficulty,
                "foundation_level": foundation or "unknown",
                "critic_required": True,
            },
        )

    def route_tutor_question(
        self,
        question: str,
        profile_id: int,
        course_id: int,
    ) -> RouterDecision:
        return RouterDecision(
            intent="answer_grounded_question",
            target_agent="tutor",
            support_agents=["retriever"],
            required_tools=[
                *AGENT_TOOL_POLICY["retriever"],
                *AGENT_TOOL_POLICY["tutor"],
            ],
            constraints={
                "question_preview": question[:120],
                "profile_id": profile_id,
                "course_id": course_id,
                "grounding_required": True,
                "citation_validation": True,
            },
        )
