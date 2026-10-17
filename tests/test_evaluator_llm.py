import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.adapters.llm_provider import LLMSettings
from app.adapters.protocols import LLMResult
from app.agents.evaluator_agents import LLMBackedEvaluatorAgent
from app.agents.evaluator_factory import build_evaluator_agent
from app.agents.rule_based_agents import RuleBasedEvaluatorAgent
from app.db.session import get_engine
from app.main import create_app


class FakeEvaluatorProvider:
    def __init__(self, fail: bool = False, content: str | None = None) -> None:
        self.fail = fail
        self.content = content

    def generate(self, messages, response_schema=None) -> LLMResult:
        if self.fail:
            raise RuntimeError("evaluator provider unavailable")
        return LLMResult(
            content=self.content or """
            {
              "score": 0.72,
              "feedback": "你的回答能区分 BFS 和 DFS 的遍历方向，但缺少复杂度和适用场景说明。",
              "weak_points": ["复杂度分析", "适用场景"],
              "misconceptions": ["只描述遍历顺序，没有说明队列和递归栈的差异"],
              "next_action": "补做一道 BFS/DFS 场景选择题，并说明时间复杂度。"
            }
            """,
            metadata={"provider": "fake"},
        )


class EvaluatorLLMTests(unittest.TestCase):
    def test_evaluator_factory_defaults_to_rule_based_without_remote_config(self) -> None:
        agent = build_evaluator_agent(LLMSettings(provider="rule_based"))
        self.assertIsInstance(agent, RuleBasedEvaluatorAgent)

    def test_llm_evaluator_uses_json_feedback(self) -> None:
        agent = LLMBackedEvaluatorAgent(FakeEvaluatorProvider())
        result = agent.evaluate(
            "应说明 BFS 使用队列，DFS 使用递归或栈，并比较适用场景。",
            {"answer": "BFS 按层，DFS 一条路走到底。"},
            5,
        )

        self.assertAlmostEqual(result.score, 0.72)
        self.assertIn("复杂度", result.feedback)
        self.assertEqual(result.mastery_updates[0]["concept_id"], 5)
        self.assertEqual(result.mastery_updates[0]["evidence"]["analysis_method"], "llm")
        self.assertIn("LLM Evaluator", result.output_summary)
        self.assertEqual(result.execution_mode, "llm")
        self.assertEqual(result.provider, "fake")
        self.assertGreaterEqual(result.duration_ms, 0)

    def test_llm_evaluator_falls_back_when_provider_fails(self) -> None:
        agent = LLMBackedEvaluatorAgent(FakeEvaluatorProvider(fail=True))
        result = agent.evaluate("应围绕链表定义说明。", {"answer": "链表由节点组成。"}, 2)

        self.assertGreaterEqual(result.score, 0.0)
        self.assertIn("Fallback reason", result.decision_basis)
        self.assertIn("evaluator provider unavailable", result.decision_basis)
        self.assertIn("rule-based", result.output_summary)
        self.assertEqual(result.execution_mode, "rule_based_fallback")
        self.assertTrue(result.fallback_used)
        self.assertIn("provider unavailable", result.fallback_reason)

    def test_llm_evaluator_rejects_invalid_json_and_falls_back_safely(self) -> None:
        agent = LLMBackedEvaluatorAgent(FakeEvaluatorProvider(content="not-json"))

        result = agent.evaluate("应围绕链表定义说明。", {"answer": "链表由节点组成。"}, 2)

        self.assertGreaterEqual(result.score, 0.0)
        self.assertLessEqual(result.score, 1.0)
        self.assertIn("rule-based", result.output_summary)
        self.assertIn("Fallback reason:", result.decision_basis)
        self.assertIn("JSON object", result.decision_basis)


class EvaluatorTraceIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "evaluator-trace.sqlite3"
        self.database_url = f"sqlite:///{database_path.as_posix()}"
        os.environ["APP_DATABASE_URL"] = self.database_url
        os.environ["LLM_PROVIDER"] = "rule_based"

    def tearDown(self) -> None:
        get_engine().dispose()
        get_engine(self.database_url).dispose()
        get_engine.cache_clear()
        os.environ.pop("APP_DATABASE_URL", None)
        os.environ.pop("LLM_PROVIDER", None)
        self.temp_dir.cleanup()

    def test_open_answer_evaluator_persists_llm_execution_metadata(self) -> None:
        evaluator = LLMBackedEvaluatorAgent(
            FakeEvaluatorProvider(),
            provider_name="openai_compatible",
            model="evaluator-test-model",
        )
        with patch("app.services.assessment_service.build_evaluator_agent", return_value=evaluator):
            with TestClient(create_app()) as client:
                demo = client.post("/api/v1/demo-data/load").json()["demo_data"]
                profile = client.get("/api/v1/student-profiles").json()[0]
                graph = client.get(f"/api/v1/courses/{demo['course_id']}/graph").json()
                quiz = client.post(
                    "/api/v1/quizzes/generate",
                    json={
                        "student_profile_id": profile["id"],
                        "concept_id": graph["concepts"][0]["id"],
                        "difficulty": "basic",
                    },
                ).json()
                attempt = client.post(
                    f"/api/v1/quizzes/{quiz['id']}/attempts",
                    json={"student_profile_id": profile["id"], "answers": {"answer": "学生开放题作答"}},
                ).json()
                run = client.get(f"/api/v1/agent-runs/{attempt['agent_run_id']}").json()

        step = next(item for item in run["steps"] if item["agent_type"] == "evaluator")
        self.assertEqual(step["execution_metadata"]["execution_mode"], "llm")
        self.assertEqual(step["execution_metadata"]["provider"], "fake")
        self.assertEqual(step["execution_metadata"]["model"], "evaluator-test-model")
        self.assertFalse(step["execution_metadata"]["fallback_used"])


if __name__ == "__main__":
    unittest.main()
