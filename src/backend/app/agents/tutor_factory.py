from app.adapters.llm_provider import LLMSettings, build_llm_provider
from app.agents.rule_based_agents import RuleBasedTutorAgent
from app.agents.tutor_agents import LLMBackedTutorAgent, TutorAgent


def build_tutor_agent(settings: LLMSettings | None = None) -> TutorAgent:
    resolved = settings or LLMSettings.from_env()
    provider = build_llm_provider(resolved)
    if provider is None:
        return RuleBasedTutorAgent()
    return LLMBackedTutorAgent(
        provider,
        fallback_agent=RuleBasedTutorAgent(),
        fallback_mode=resolved.fallback_mode,
        provider_name=resolved.provider,
        model=resolved.model,
    )
