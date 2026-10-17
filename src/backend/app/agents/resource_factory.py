from app.adapters.llm_provider import LLMSettings, build_llm_provider
from app.agents.resource_agents import LLMBackedResourceAgent, ResourceAgent
from app.agents.rule_based_agents import RuleBasedResourceAgent


def build_resource_agent(settings: LLMSettings | None = None) -> ResourceAgent:
    resolved = settings or LLMSettings.from_env()
    provider = build_llm_provider(resolved, purpose="resource")
    if provider is None:
        return RuleBasedResourceAgent()
    return LLMBackedResourceAgent(
        provider,
        fallback_agent=RuleBasedResourceAgent(),
        fallback_mode=resolved.fallback_mode,
        provider_name=resolved.provider,
        model=resolved.model,
    )
