from app.adapters.llm_provider import LLMSettings, build_llm_provider
from app.agents.evaluator_agents import EvaluatorAgent, LLMBackedEvaluatorAgent
from app.agents.rule_based_agents import RuleBasedEvaluatorAgent


def build_evaluator_agent(settings: LLMSettings | None = None) -> EvaluatorAgent:
    resolved = settings or LLMSettings.from_env()
    provider = build_llm_provider(resolved, purpose="evaluator")
    if provider is None:
        return RuleBasedEvaluatorAgent()
    return LLMBackedEvaluatorAgent(
        provider,
        fallback_agent=RuleBasedEvaluatorAgent(),
        fallback_mode=resolved.fallback_mode,
        provider_name=resolved.provider,
        model=resolved.model,
    )
