import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.adapters.llm_provider import LLMProviderError, LLMSettings
from app.adapters.protocols import LLMResult
from app.agents.profile_builder_agents import (
    LLMProfileBuilderAgent,
    ProfileBuildResult,
    RuleBasedProfileBuilderAgent,
    build_profile_builder_agent,
)
from app.db.session import get_engine, get_session_factory
from app.main import create_app
from app.models import AgentRunStep
from app.schemas import StudentProfileCreate, StudentProfileDialogueCreate


class FakeLLMProvider:
    def __init__(self, content: str) -> None:
        self.content = content
        self.messages: list[dict[str, str]] = []
        self.response_schema = None

    def generate(self, messages, response_schema=None) -> LLMResult:
        self.messages = messages
        self.response_schema = response_schema
        return LLMResult(
            content=self.content,
            metadata={"provider": "openai_compatible", "model": "profile-test-model"},
        )


class RaisingLLMProvider:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def generate(self, messages, response_schema=None) -> LLMResult:
        raise self.error


class ProfileBuilderLLMTests(unittest.TestCase):
    def test_settings_and_factory_enable_profile_builder_independently(self) -> None:
        settings = LLMSettings(
            provider="openai_compatible",
            base_url="https://example.invalid/v1",
            api_key="test-only-key",
            model="profile-test-model",
            enable_for_profile_builder=True,
        )

        agent = build_profile_builder_agent(settings)

        self.assertIsInstance(agent, LLMProfileBuilderAgent)
        self.assertTrue(settings.can_call_remote("profile_builder"))
        disabled = LLMSettings(
            provider="openai_compatible",
            base_url="https://example.invalid/v1",
            api_key="test-only-key",
            model="profile-test-model",
        )
        self.assertIsInstance(build_profile_builder_agent(disabled), RuleBasedProfileBuilderAgent)

        with patch.dict(
            os.environ,
            {
                "LLM_PROVIDER": "openai_compatible",
                "LLM_BASE_URL": "https://example.invalid/v1",
                "LLM_API_KEY": "test-only-key",
                "LLM_MODEL": "profile-test-model",
                "LLM_ENABLE_FOR_PROFILE_BUILDER": "true",
            },
            clear=True,
        ):
            self.assertTrue(LLMSettings.from_env().enable_for_profile_builder)

    def test_llm_builder_returns_six_valid_dimensions_and_preserves_explicit_context(self) -> None:
        provider = FakeLLMProvider(
            json.dumps(
                {
                    "profile_type": "algorithm_practice",
                    "learning_goal": "通过代码实践掌握图算法",
                    "foundation_level": "intermediate",
                    "learning_preference": "code_driven",
                    "available_time": "工作日每天 45 分钟",
                    "weak_points": ["图的存储", "最短路径"],
                    "resource_preference": "代码实操案例",
                    "evidence_summary": "有编程基础，偏好代码实践，时间有限。",
                },
                ensure_ascii=False,
            )
        )
        agent = LLMProfileBuilderAgent(
            provider,
            provider_name="openai_compatible",
            model="profile-test-model",
        )
        payload = StudentProfileDialogueCreate(
            dialogue="我不是零基础，概念能看懂，但不喜欢长篇讲义，希望通过写代码掌握图算法。",
            profile_type="exam_sprint",
            user_id=42,
        )

        result = agent.build(payload)

        self.assertEqual(result.execution_mode, "llm")
        self.assertFalse(result.fallback_used)
        self.assertEqual(result.profile.profile_type, "exam_sprint")
        self.assertEqual(result.profile.user_id, 42)
        self.assertEqual(result.profile.level, "intermediate")
        self.assertEqual(result.profile.preferences["learning_preference"], "code_driven")
        self.assertEqual(result.profile.preferences["weak_points"], "图的存储、最短路径")
        self.assertNotIn(payload.dialogue, result.evidence_summary)
        self.assertEqual(
            {
                "learning_goal",
                "foundation_level",
                "learning_preference",
                "available_time",
                "weak_points",
                "resource_preference",
            },
            set(result.profile.preferences).intersection(
                {
                    "learning_goal",
                    "foundation_level",
                    "learning_preference",
                    "available_time",
                    "weak_points",
                    "resource_preference",
                }
            ),
        )
        prompt = "\n".join(message["content"] for message in provider.messages)
        self.assertIn(payload.dialogue, prompt)
        self.assertIsNotNone(provider.response_schema)

    def test_invalid_llm_json_falls_back_with_a_sanitized_reason(self) -> None:
        agent = LLMProfileBuilderAgent(
            FakeLLMProvider("not-json"),
            provider_name="openai_compatible",
            model="profile-test-model",
        )

        result = agent.build(StudentProfileDialogueCreate(dialogue="我想用例题学习链表，每天一小时。"))

        self.assertEqual(result.execution_mode, "rule_based_fallback")
        self.assertTrue(result.fallback_used)
        self.assertIn("ValueError", result.fallback_reason)
        self.assertNotIn("not-json", result.fallback_reason)
        self.assertEqual(result.profile.preferences["profile_origin"], "user_dialogue")

    def test_provider_timeout_and_http_error_both_fall_back(self) -> None:
        payload = StudentProfileDialogueCreate(dialogue="我想通过例题复习图算法。")
        for error in (
            TimeoutError("request timed out"),
            LLMProviderError("LLM provider request failed: HTTP 503"),
        ):
            with self.subTest(error=type(error).__name__):
                result = LLMProfileBuilderAgent(RaisingLLMProvider(error)).build(payload)
                self.assertEqual(result.execution_mode, "rule_based_fallback")
                self.assertTrue(result.fallback_used)
                self.assertTrue(result.fallback_reason)

    def test_llm_builder_accepts_provider_profile_type_key_casing(self) -> None:
        provider = FakeLLMProvider(
            json.dumps(
                {
                    "ProfileType": "exam_sprint",
                    "learning_goal": "掌握最短路径算法",
                    "foundation_level": "intermediate",
                    "learning_preference": "code_driven",
                    "available_time": "每天 40 分钟",
                    "weak_points": ["最短路径"],
                    "resource_preference": "代码实操案例",
                    "evidence_summary": "已有线性结构基础，需要加强图算法。",
                },
                ensure_ascii=False,
            )
        )

        result = LLMProfileBuilderAgent(provider).build(
            StudentProfileDialogueCreate(dialogue="我会链表和栈，希望通过代码学习最短路径。")
        )

        self.assertEqual(result.execution_mode, "llm")
        self.assertEqual(result.profile.profile_type, "exam_sprint")

    def test_llm_builder_normalizes_english_resource_type_without_fallback(self) -> None:
        provider = FakeLLMProvider(
            json.dumps(
                {
                    "profile_type": "algorithm_practice",
                    "learning_goal": "master graph algorithms",
                    "foundation_level": "intermediate",
                    "learning_preference": "code_driven",
                    "available_time": "six hours weekly",
                    "weak_points": ["shortest paths"],
                    "resource_preference": "coding_exercises",
                }
            )
        )

        result = LLMProfileBuilderAgent(provider).build(
            StudentProfileDialogueCreate(dialogue="I prefer coding exercises for graph algorithms.")
        )

        self.assertEqual(result.execution_mode, "llm")
        self.assertFalse(result.fallback_used)
        self.assertEqual(result.profile.preferences["resource_preference"], "代码实操案例")


class ProfileBuilderHistoryIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "profile-builder.sqlite3"
        self.database_url = f"sqlite:///{database_path.as_posix()}"
        os.environ["APP_DATABASE_URL"] = self.database_url

    def tearDown(self) -> None:
        get_engine().dispose()
        get_engine(self.database_url).dispose()
        get_engine.cache_clear()
        os.environ.pop("APP_DATABASE_URL", None)
        self.temp_dir.cleanup()

    def test_dialogue_api_keeps_contract_and_records_llm_runtime_evidence(self) -> None:
        profile = StudentProfileCreate(
            user_id=None,
            profile_type="algorithm_practice",
            goal="通过代码练习掌握链表",
            level="intermediate",
            preferences={
                "profile_origin": "user_dialogue",
                "learning_goal": "通过代码练习掌握链表",
                "foundation_level": "intermediate",
                "learning_preference": "code_driven",
                "available_time": "每天 1 小时",
                "weak_points": "链表删除",
                "resource_preference": "代码实操案例",
            },
            time_budget="每天 1 小时",
        )
        fake_result = ProfileBuildResult(
            profile=profile,
            execution_mode="llm",
            provider="openai_compatible",
            model="profile-test-model",
            fallback_used=False,
            fallback_reason=None,
            evidence_summary="偏好代码实践，薄弱点为链表删除。",
            duration_ms=25,
        )
        fake_agent = unittest.mock.Mock()
        fake_agent.build.return_value = fake_result
        dialogue = "这段完整对话不得原样写入画像历史记录。"

        with patch("app.services.profile_service.build_profile_builder_agent", return_value=fake_agent):
            with TestClient(create_app()) as client:
                response = client.post("/api/v1/student-profiles/from-dialogue", json={"dialogue": dialogue})
                self.assertEqual(response.status_code, 200)
                created = response.json()
                history = client.get(f"/api/v1/student-profiles/{created['id']}/history").json()[0]
                run = client.get(f"/api/v1/agent-runs/{history['agent_run_id']}").json()

        self.assertEqual(created["goal"], profile.goal)
        self.assertEqual(history["trigger_type"], "dialogue")
        self.assertIn("llm", history["reason"])
        self.assertNotIn(dialogue, json.dumps(history, ensure_ascii=False))
        self.assertIn("execution_mode=llm", run["steps"][0]["decision_basis"])
        self.assertIn("provider=openai_compatible", run["steps"][0]["decision_basis"])
        self.assertEqual(run["steps"][0]["duration_ms"], 25)
        self.assertEqual(run["steps"][0]["execution_metadata"]["execution_mode"], "llm")
        self.assertEqual(run["steps"][0]["execution_metadata"]["provider"], "openai_compatible")
        self.assertEqual(run["steps"][0]["execution_metadata"]["model"], "profile-test-model")
        self.assertFalse(run["steps"][0]["execution_metadata"]["fallback_used"])

        with get_session_factory(self.database_url)() as session:
            step = session.scalar(select(AgentRunStep).where(AgentRunStep.agent_run_id == history["agent_run_id"]))
            self.assertEqual(step.agent_type, "profile_builder")

    def test_dialogue_api_records_rule_based_fallback_reason(self) -> None:
        profile = StudentProfileCreate(
            profile_type="weak_foundation",
            goal="复习链表",
            level="beginner",
            preferences={
                "profile_origin": "user_dialogue",
                "learning_goal": "复习链表",
                "foundation_level": "beginner",
                "learning_preference": "step_by_step",
                "available_time": "每天 30 分钟",
                "weak_points": "链表",
                "resource_preference": "讲解文档",
            },
            time_budget="每天 30 分钟",
        )
        fake_result = ProfileBuildResult(
            profile=profile,
            execution_mode="rule_based_fallback",
            provider="openai_compatible",
            model="profile-test-model",
            fallback_used=True,
            fallback_reason="ValidationError: response schema validation failed",
            evidence_summary="规则回退后抽取基础画像。",
            duration_ms=12,
        )
        fake_agent = unittest.mock.Mock()
        fake_agent.build.return_value = fake_result

        with patch("app.services.profile_service.build_profile_builder_agent", return_value=fake_agent):
            with TestClient(create_app()) as client:
                created = client.post(
                    "/api/v1/student-profiles/from-dialogue",
                    json={"dialogue": "我想复习链表。"},
                ).json()
                history = client.get(f"/api/v1/student-profiles/{created['id']}/history").json()[0]
                run = client.get(f"/api/v1/agent-runs/{history['agent_run_id']}").json()

        self.assertIn("rule_based_fallback", history["reason"])
        self.assertIn("fallback_used=true", run["steps"][0]["decision_basis"])
        self.assertIn("ValidationError", run["steps"][0]["decision_basis"])
        self.assertEqual(run["steps"][0]["execution_metadata"]["execution_mode"], "rule_based_fallback")
        self.assertTrue(run["steps"][0]["execution_metadata"]["fallback_used"])
        self.assertIn("ValidationError", run["steps"][0]["execution_metadata"]["fallback_reason"])


if __name__ == "__main__":
    unittest.main()
