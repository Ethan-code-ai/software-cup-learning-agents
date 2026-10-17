import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.adapters.llm_provider import LLMSettings
from app.adapters.protocols import LLMResult
from app.agents.quiz_agents import LLMQuizAgent, QuizContext
from app.agents.quiz_factory import build_quiz_agent
from app.agents.critic_agents import RuleBasedCriticAgent
from app.agents.rule_based_agents import QuizAgentResult, RuleBasedQuizAgent
from app.db.session import get_engine
from app.main import create_app
from app.schemas import KnowledgeSearchResult


class FakeQuizProvider:
    def __init__(self, payload: dict | None = None, error: Exception | None = None) -> None:
        self.payload = payload or _multiple_choice_payload()
        self.error = error
        self.calls = 0
        self.messages: list[dict[str, str]] = []

    def generate(self, messages, response_schema=None) -> LLMResult:
        self.calls += 1
        self.messages = messages
        if self.error is not None:
            raise self.error
        return LLMResult(
            content=json.dumps(self.payload, ensure_ascii=False),
            metadata={"provider": "openai_compatible", "model": "quiz-test-model"},
        )


class AdaptiveQuizProvider(FakeQuizProvider):
    def generate(self, messages, response_schema=None) -> LLMResult:
        prompt = messages[-1]["content"]
        if "algorithm_practice" in prompt:
            self.payload = {
                "question_type": "code_analysis",
                "question": "阅读代码并说明 BFS 的出队顺序。\n```python\nnode = queue.popleft()\n```",
                "options": [],
                "answer": "按层依次出队。",
                "explanation": "课程资料说明 BFS 使用队列逐层扩展。",
                "difficulty": "medium",
                "concept_tags": ["广度优先搜索"],
                "source_refs": ["document:1#chunk:0"],
            }
        else:
            self.payload = _multiple_choice_payload()
        return super().generate(messages, response_schema)


class PromptGroundedQuizProvider(FakeQuizProvider):
    def generate(self, messages, response_schema=None) -> LLMResult:
        match = re.search(r'"source_ref":\s*"([^"]+)"', messages[-1]["content"])
        if match:
            self.payload = {**_multiple_choice_payload(), "source_refs": [match.group(1)]}
        return super().generate(messages, response_schema)


class CriticRejectedQuizProvider(PromptGroundedQuizProvider):
    def generate(self, messages, response_schema=None) -> LLMResult:
        difficulty_match = re.search(r"目标难度（difficulty 必须原样返回）：([^\n]+)", messages[-1]["content"])
        source_match = re.search(r'"source_ref":\s*"([^"]+)"', messages[-1]["content"])
        self.payload = {
            **_multiple_choice_payload(),
            "question": "红黑树手写旋转后，BFS 应使用哪一种结构？",
            "difficulty": difficulty_match.group(1).strip() if difficulty_match else "medium",
            "source_refs": [source_match.group(1)] if source_match else ["document:1#chunk:0"],
        }
        return FakeQuizProvider.generate(self, messages, response_schema)


class QuizLLMAgentTests(unittest.TestCase):
    def test_factory_uses_quiz_specific_flag(self) -> None:
        settings = LLMSettings(
            provider="openai_compatible",
            base_url="https://example.invalid/v1",
            api_key="test-only-key",
            model="quiz-test-model",
            enable_for_quiz=True,
        )

        self.assertIsInstance(build_quiz_agent(settings), LLMQuizAgent)
        self.assertTrue(settings.can_call_remote("quiz"))
        with patch.dict(
            os.environ,
            {
                "LLM_PROVIDER": "openai_compatible",
                "LLM_BASE_URL": "https://example.invalid/v1",
                "LLM_API_KEY": "test-only-key",
                "LLM_MODEL": "quiz-test-model",
                "LLM_ENABLE_FOR_QUIZ": "true",
            },
            clear=True,
        ):
            self.assertTrue(LLMSettings.from_env().enable_for_quiz)

    def test_valid_llm_quiz_uses_grounded_schema_and_context(self) -> None:
        provider = FakeQuizProvider()
        agent = LLMQuizAgent(provider, provider_name="openai_compatible", model="quiz-test-model")

        result = agent.generate(
            "广度优先搜索",
            "medium",
            [_chunk()],
            QuizContext(
                profile_preferences={"profile_type": "exam_sprint", "weak_points": "队列"},
                mastery_score=0.42,
                recent_errors=["混淆队列与栈"],
            ),
        )

        self.assertEqual(result.question_type, "multiple_choice")
        self.assertEqual(result.options, ["A. 栈", "B. 队列", "C. 堆", "D. 集合"])
        self.assertEqual(result.source_refs[0]["source_ref"], "document:1#chunk:0")
        self.assertEqual(result.execution_mode, "llm")
        self.assertFalse(result.fallback_used)
        prompt = provider.messages[-1]["content"]
        self.assertIn("0.42", prompt)
        self.assertIn("混淆队列与栈", prompt)
        self.assertNotIn("test-only-key", prompt)

    def test_multiple_choice_answer_text_is_normalized_to_unique_option_label(self) -> None:
        payload = {**_multiple_choice_payload(), "answer": "队列"}

        result = LLMQuizAgent(FakeQuizProvider(payload)).generate(
            "广度优先搜索",
            "medium",
            [_chunk()],
            QuizContext(profile_preferences={}),
        )

        self.assertEqual(result.execution_mode, "llm")
        self.assertEqual(result.answer, "B")
        self.assertFalse(result.fallback_used)

    def test_different_profiles_produce_different_question_types(self) -> None:
        provider = AdaptiveQuizProvider()
        agent = LLMQuizAgent(provider)
        exam_result = agent.generate(
            "广度优先搜索",
            "medium",
            [_chunk()],
            QuizContext(profile_preferences={"profile_type": "exam_sprint"}),
        )
        coding_result = agent.generate(
            "广度优先搜索",
            "medium",
            [_chunk()],
            QuizContext(profile_preferences={"profile_type": "algorithm_practice"}),
        )

        self.assertNotEqual(exam_result.question_type, coding_result.question_type)
        self.assertNotEqual(exam_result.question, coding_result.question)

    def test_fake_reference_invalid_json_timeout_and_empty_retrieval_fall_back(self) -> None:
        invalid_reference = _multiple_choice_payload()
        invalid_reference["source_refs"] = ["document:999#chunk:999"]
        fabricated_text_reference = _multiple_choice_payload()
        fabricated_text_reference["explanation"] = "依据 document:999#chunk:999 可知答案为 B。"
        cases = [
            FakeQuizProvider(invalid_reference),
            FakeQuizProvider(fabricated_text_reference),
            FakeQuizProvider(error=TimeoutError("quiz timeout")),
            FakeQuizProvider(error=ValueError("invalid JSON")),
        ]
        for provider in cases:
            with self.subTest(provider=provider):
                result = LLMQuizAgent(provider).generate(
                    "广度优先搜索",
                    "medium",
                    [_chunk()],
                    QuizContext(profile_preferences={}),
                )
                self.assertEqual(result.execution_mode, "rule_based_fallback")
                self.assertTrue(result.fallback_used)
                self.assertTrue(result.fallback_reason)
                self.assertEqual(
                    {item["source_ref"] for item in result.source_refs},
                    {"document:1#chunk:0"},
                )

        unused_provider = FakeQuizProvider()
        no_evidence = LLMQuizAgent(unused_provider).generate(
            "广度优先搜索",
            "medium",
            [],
            QuizContext(profile_preferences={}),
        )
        self.assertEqual(unused_provider.calls, 0)
        self.assertEqual(no_evidence.execution_mode, "rule_based_fallback")
        self.assertEqual(no_evidence.source_refs, [])
        self.assertIn("retrieval", no_evidence.fallback_reason.lower())

    def test_english_quiz_is_rejected_and_falls_back_to_chinese(self) -> None:
        english_payload = {
            "question_type": "multiple_choice",
            "question": "Which statement about queues is correct?",
            "options": ["A. Queue is used by DFS", "B. Queue is used by BFS"],
            "answer": "B",
            "explanation": "BFS expands nodes level by level with a queue.",
            "difficulty": "medium",
            "concept_tags": ["queue", "BFS"],
            "source_refs": ["document:1#chunk:0"],
        }

        result = LLMQuizAgent(FakeQuizProvider(english_payload)).generate(
            "队列",
            "medium",
            [_chunk()],
            QuizContext(profile_preferences={}),
        )

        self.assertEqual(result.execution_mode, "rule_based_fallback")
        self.assertTrue(result.fallback_used)
        self.assertIn("Chinese", result.fallback_reason)
        self.assertRegex(result.question, r"[\u4e00-\u9fff]")
        self.assertTrue(all(re.search(r"[\u4e00-\u9fff]", option) for option in result.options))

    def test_schema_supports_all_five_required_question_types(self) -> None:
        payloads = {
            "multiple_choice": _multiple_choice_payload(),
            "fill_blank": _open_question_payload("fill_blank", "BFS 通常使用____维护待访问节点。"),
            "short_answer": _open_question_payload("short_answer", "简述 BFS 的核心思想。"),
            "application": _open_question_payload("application", "说明 BFS 在无权图最短路中的应用。"),
            "code_analysis": _open_question_payload(
                "code_analysis",
                "分析出队操作。\n```python\nnode = queue.popleft()\n```",
            ),
        }
        for question_type, payload in payloads.items():
            with self.subTest(question_type=question_type):
                result = LLMQuizAgent(FakeQuizProvider(payload)).generate(
                    "广度优先搜索",
                    "medium",
                    [_chunk()],
                    QuizContext(profile_preferences={}),
                )
                self.assertEqual(result.execution_mode, "llm")
                self.assertEqual(result.question_type, question_type)

    def test_critic_rejects_fake_references_incomplete_choices_code_without_fence_and_english(self) -> None:
        critic = RuleBasedCriticAgent()
        base = dict(
            question="题目",
            answer="A",
            explanation="解析",
            concept_tags=["广度优先搜索"],
            input_summary="input",
            output_summary="output",
            decision_basis="basis",
        )
        fake_reference = QuizAgentResult(
            **base,
            question_type="short_answer",
            source_refs=[{"source_ref": "document:999#chunk:999"}],
        )
        incomplete_choice = QuizAgentResult(
            **base,
            question_type="multiple_choice",
            options=["A. 唯一选项"],
            source_refs=[{"source_ref": "document:1#chunk:0"}],
        )
        code_without_fence = QuizAgentResult(
            **base,
            question_type="code_analysis",
            source_refs=[{"source_ref": "document:1#chunk:0"}],
        )
        english_quiz = QuizAgentResult(
            **{
                **base,
                "question": "Which queue statement is correct?",
                "explanation": "BFS uses a queue.",
            },
            question_type="multiple_choice",
            options=["A. Stack", "B. Queue"],
            source_refs=[{"source_ref": "document:1#chunk:0"}],
        )

        allowed = {"document:1#chunk:0"}
        self.assertFalse(critic.review_quiz(fake_reference, "medium", {}, allowed).approved)
        self.assertFalse(critic.review_quiz(incomplete_choice, "medium", {}, allowed).approved)
        self.assertFalse(critic.review_quiz(code_without_fence, "medium", {}, allowed).approved)
        self.assertFalse(critic.review_quiz(english_quiz, "medium", {}, allowed).approved)


class QuizLLMApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "quiz-llm.sqlite3"
        self.database_url = f"sqlite:///{database_path.as_posix()}"
        os.environ["APP_DATABASE_URL"] = self.database_url

    def tearDown(self) -> None:
        get_engine().dispose()
        get_engine(self.database_url).dispose()
        get_engine.cache_clear()
        os.environ.pop("APP_DATABASE_URL", None)
        self.temp_dir.cleanup()

    def test_api_returns_quiz_metadata_trace_and_uses_deterministic_objective_scoring(self) -> None:
        agent = LLMQuizAgent(PromptGroundedQuizProvider(), provider_name="openai_compatible", model="quiz-test-model")
        with patch("app.services.assessment_service.build_quiz_agent", return_value=agent):
            with TestClient(create_app()) as client:
                demo = client.post("/api/v1/demo-data/load").json()["demo_data"]
                profile = client.get("/api/v1/student-profiles").json()[1]
                graph = client.get(f"/api/v1/courses/{demo['course_id']}/graph").json()
                concept = next(item for item in graph["concepts"] if item["slug"] == "bfs-dfs")
                response = client.post(
                    "/api/v1/quizzes/generate",
                    json={"student_profile_id": profile["id"], "concept_id": concept["id"], "difficulty": "medium"},
                )

                self.assertEqual(response.status_code, 200)
                body = response.json()
                item = body["items"][0]
                self.assertEqual(item["question_type"], "multiple_choice")
                self.assertEqual(item["options"][1], "B. 队列")
                self.assertTrue(item["source_refs"][0]["source_ref"])
                self.assertNotIn("document:999", item["source_refs"][0]["source_ref"])
                self.assertEqual(body["execution_mode"], "llm")
                self.assertFalse(body["fallback_used"])

                run = client.get(f"/api/v1/agent-runs/{body['agent_run_id']}").json()
                quiz_step = next(step for step in run["steps"] if step["agent_type"] == "quiz")
                self.assertIn("execution_mode=llm", quiz_step["decision_basis"])
                self.assertIn("source_refs=", quiz_step["decision_basis"])
                self.assertEqual(quiz_step["execution_metadata"]["execution_mode"], "llm")
                self.assertEqual(quiz_step["execution_metadata"]["provider"], "openai_compatible")
                self.assertEqual(quiz_step["execution_metadata"]["model"], "quiz-test-model")
                self.assertTrue(quiz_step["execution_metadata"]["source_refs"])

                correct = client.post(
                    f"/api/v1/quizzes/{body['id']}/attempts",
                    json={"student_profile_id": profile["id"], "answers": {"answer": "B"}},
                ).json()
                wrong = client.post(
                    f"/api/v1/quizzes/{body['id']}/attempts",
                    json={"student_profile_id": profile["id"], "answers": {"answer": "A"}},
                ).json()
                self.assertEqual(correct["score"], 1.0)
                self.assertEqual(wrong["score"], 0.0)
                objective_run = client.get(f"/api/v1/agent-runs/{correct['agent_run_id']}").json()
                evaluator_step = next(step for step in objective_run["steps"] if step["agent_type"] == "evaluator")
                self.assertIn("evaluation_mode=deterministic", evaluator_step["decision_basis"])
                self.assertEqual(evaluator_step["execution_metadata"]["execution_mode"], "rule_based")
                self.assertEqual(evaluator_step["execution_metadata"]["provider"], "rule_based")

    def test_provider_failure_returns_grounded_fallback_that_completes_evaluation_loop(self) -> None:
        agent = LLMQuizAgent(
            FakeQuizProvider(error=TimeoutError("quiz provider timeout")),
            provider_name="openai_compatible",
            model="quiz-test-model",
        )
        with patch("app.services.assessment_service.build_quiz_agent", return_value=agent):
            with TestClient(create_app()) as client:
                demo = client.post("/api/v1/demo-data/load").json()["demo_data"]
                profile = client.get("/api/v1/student-profiles").json()[0]
                graph = client.get(f"/api/v1/courses/{demo['course_id']}/graph").json()
                response = client.post(
                    "/api/v1/quizzes/generate",
                    json={
                        "student_profile_id": profile["id"],
                        "concept_id": graph["concepts"][0]["id"],
                        "difficulty": "basic",
                    },
                )

                self.assertEqual(response.status_code, 200)
                quiz = response.json()
                self.assertTrue(quiz["fallback_used"])
                self.assertIn("TimeoutError", quiz["fallback_reason"])
                self.assertEqual(quiz["execution_mode"], "rule_based_fallback")
                self.assertTrue(quiz["items"][0]["source_refs"])

                attempt = client.post(
                    f"/api/v1/quizzes/{quiz['id']}/attempts",
                    json={
                        "student_profile_id": profile["id"],
                        "answers": {"answer": quiz["items"][0]["answer"]},
                    },
                )
                self.assertEqual(attempt.status_code, 200)
                self.assertGreaterEqual(attempt.json()["score"], 0.0)
                self.assertTrue(attempt.json()["feedback"])

    def test_repeated_critic_rejection_forces_rule_based_safety_fallback(self) -> None:
        agent = LLMQuizAgent(
            CriticRejectedQuizProvider(),
            provider_name="openai_compatible",
            model="quiz-test-model",
        )
        with patch("app.services.assessment_service.build_quiz_agent", return_value=agent):
            with TestClient(create_app()) as client:
                demo = client.post("/api/v1/demo-data/load").json()["demo_data"]
                weak_profile = client.get("/api/v1/student-profiles").json()[0]
                graph = client.get(f"/api/v1/courses/{demo['course_id']}/graph").json()
                response = client.post(
                    "/api/v1/quizzes/generate",
                    json={
                        "student_profile_id": weak_profile["id"],
                        "concept_id": graph["concepts"][0]["id"],
                        "difficulty": "medium",
                    },
                )

                self.assertEqual(response.status_code, 200)
                quiz = response.json()
                self.assertEqual(quiz["execution_mode"], "rule_based_critic_fallback")
                self.assertTrue(quiz["fallback_used"])
                self.assertIn("Critic", quiz["fallback_reason"])
                self.assertNotIn("红黑树", quiz["items"][0]["question"])


def _multiple_choice_payload() -> dict:
    return {
        "question_type": "multiple_choice",
        "question": "BFS 通常使用哪一种数据结构维护待访问节点？",
        "options": ["A. 栈", "B. 队列", "C. 堆", "D. 集合"],
        "answer": "B",
        "explanation": "课程资料说明 BFS 使用队列逐层扩展节点。",
        "difficulty": "medium",
        "concept_tags": ["广度优先搜索", "队列"],
        "source_refs": ["document:1#chunk:0"],
    }


def _open_question_payload(question_type: str, question: str) -> dict:
    return {
        "question_type": question_type,
        "question": question,
        "options": [],
        "answer": "队列",
        "explanation": "课程资料说明 BFS 使用队列逐层扩展节点。",
        "difficulty": "medium",
        "concept_tags": ["广度优先搜索"],
        "source_refs": ["document:1#chunk:0"],
    }


def _chunk() -> KnowledgeSearchResult:
    return KnowledgeSearchResult(
        chunk_id=1,
        content="广度优先搜索使用队列逐层扩展节点，适合求无权图最短路径。",
        score=1.0,
        source_ref="document:1#chunk:0",
        metadata={"source_title": "数据结构课程资料", "excerpt": "广度优先搜索使用队列逐层扩展节点。"},
    )


if __name__ == "__main__":
    unittest.main()
