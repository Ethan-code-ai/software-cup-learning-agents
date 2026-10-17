import unittest

from app.adapters.llm_provider import LLMSettings
from app.adapters.protocols import LLMResult
from app.agents.resource_agents import LLMBackedResourceAgent
from app.agents.resource_factory import build_resource_agent
from app.agents.rule_based_agents import RuleBasedResourceAgent
from app.schemas import KnowledgeSearchResult


class FakeResourceProvider:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    def generate(self, messages, response_schema=None) -> LLMResult:
        if self.fail:
            raise RuntimeError("resource provider unavailable")
        return LLMResult(
            content="【LLM 讲解文档】链表\n资料依据：[1] demo.md#linked-list\n主体内容：链表适合频繁插入删除。",
            metadata={"provider": "fake"},
        )


class CapturingResourceProvider(FakeResourceProvider):
    def __init__(self) -> None:
        super().__init__()
        self.messages = []

    def generate(self, messages, response_schema=None) -> LLMResult:
        self.messages = messages
        return super().generate(messages, response_schema)


class ResourceLLMTests(unittest.TestCase):
    def test_resource_factory_defaults_to_rule_based_without_remote_config(self) -> None:
        agent = build_resource_agent(LLMSettings(provider="rule_based"))
        self.assertIsInstance(agent, RuleBasedResourceAgent)

    def test_llm_resource_agent_uses_provider_content(self) -> None:
        agent = LLMBackedResourceAgent(FakeResourceProvider())
        result = agent.generate("链表", "掌握链表插入", "guided_note", [_chunk()], {"learning_preference": "step_by_step"})

        self.assertIn("LLM 讲解文档", result.content)
        self.assertTrue(result.source_refs)
        self.assertIn("LLMProvider adapter", result.decision_basis)
        self.assertIn("LLM provider", result.output_summary)
        self.assertEqual(result.execution_mode, "llm")
        self.assertEqual(result.provider, "fake")
        self.assertEqual(result.source_refs[0]["source_ref"], "demo.md#linked-list")
        self.assertGreaterEqual(result.duration_ms, 0)

    def test_llm_resource_agent_falls_back_when_provider_fails(self) -> None:
        agent = LLMBackedResourceAgent(FakeResourceProvider(fail=True))
        result = agent.generate("链表", "掌握链表插入", "coding_case", [_chunk()], {"learning_preference": "code_driven"})

        self.assertIn("代码实操案例", result.content)
        self.assertIn("Fallback reason", result.decision_basis)
        self.assertIn("resource provider unavailable", result.decision_basis)
        self.assertIn("rule-based", result.output_summary)
        self.assertEqual(result.execution_mode, "rule_based_fallback")
        self.assertTrue(result.fallback_used)
        self.assertIn("provider unavailable", result.fallback_reason)

    def test_llm_resource_prompt_requires_type_specific_outputs(self) -> None:
        provider = CapturingResourceProvider()
        agent = LLMBackedResourceAgent(provider)

        agent.generate("复杂度分析", "掌握复杂度", "coding_case", [_chunk()], {})
        coding_prompt = provider.messages[-1]["content"]
        self.assertIn("```python", coding_prompt)
        self.assertIn("输入样例", coding_prompt)
        self.assertIn("预期输出", coding_prompt)

        agent.generate("复杂度分析", "掌握复杂度", "mind_map", [_chunk()], {})
        map_prompt = provider.messages[-1]["content"]
        self.assertIn("中心主题", map_prompt)
        self.assertIn("分支：", map_prompt)

        agent.generate("复杂度分析", "掌握复杂度", "practice_questions", [_chunk()], {})
        practice_prompt = provider.messages[-1]["content"]
        self.assertIn("题目 1", practice_prompt)
        self.assertIn("答案提示", practice_prompt)


def _chunk() -> KnowledgeSearchResult:
    return KnowledgeSearchResult(
        chunk_id=1,
        content="链表由节点组成，插入删除时主要调整指针关系。",
        score=1.0,
        source_ref="demo.md#linked-list",
        metadata={"concept_slug": "linked-list"},
    )


if __name__ == "__main__":
    unittest.main()
