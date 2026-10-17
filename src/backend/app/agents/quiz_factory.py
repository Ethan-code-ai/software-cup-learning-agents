from app.adapters.llm_provider import LLMSettings, build_llm_provider
from app.agents.quiz_agents import LLMQuizAgent, QuizAgent
from app.agents.rule_based_agents import RuleBasedQuizAgent


def build_quiz_agent(settings: LLMSettings | None = None) -> QuizAgent | RuleBasedQuizAgent:
    resolved = settings or LLMSettings.from_env()
    provider = build_llm_provider(resolved, purpose="quiz")
    if provider is None:
        return RuleBasedQuizAgent()
    return LLMQuizAgent(
        provider,
        fallback_mode=resolved.fallback_mode,
        provider_name=resolved.provider,
        model=resolved.model,
    )
