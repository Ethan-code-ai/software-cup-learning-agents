import json
import os
import socket
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.error import URLError

from fastapi.testclient import TestClient

from app.adapters.llm_provider import LLMProviderError, LLMSettings, OpenAICompatibleLLMProvider
from app.adapters.protocols import LLMResult
from app.db.session import get_engine
from app.main import create_app
from app.agents.rule_based_agents import RuleBasedTutorAgent
from app.agents.tutor_agents import LLMBackedTutorAgent, select_tutor_evidence
from app.agents.tutor_factory import build_tutor_agent
from app.schemas import KnowledgeSearchResult
from app.services.citation_service import validate_citations


class FakeProvider:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    def generate(self, messages, response_schema=None) -> LLMResult:
        if self.fail:
            raise RuntimeError("provider unavailable")
        return LLMResult(
            content=json.dumps(
                {
                    "sections": [
                        {"heading": "direct_answer", "content": "这是来自模拟 LLM provider 的回答。", "evidence_ids": ["E1"]},
                        {"heading": "profile_adaptation", "content": "根据当前基础先比较核心差异。", "evidence_ids": ["E1"]},
                        {"heading": "next_step", "content": "完成一个小例子验证理解。", "evidence_ids": ["E1"]},
                    ]
                },
                ensure_ascii=False,
            ),
            metadata={"provider": "fake"},
        )


class NoContextProvider:
    def generate(self, messages, response_schema=None) -> LLMResult:
        return LLMResult(
            content="No retrieved course chunks are available, so I cannot answer.",
            metadata={"provider": "fake"},
        )


class UnexpectedCallProvider:
    def generate(self, messages, response_schema=None) -> LLMResult:
        raise AssertionError("provider must not be called without retrieved evidence")


class PromptCaptureProvider:
    def __init__(self) -> None:
        self.messages = []

    def generate(self, messages, response_schema=None) -> LLMResult:
        self.messages = messages
        return LLMResult(
            content=json.dumps(
                {
                    "sections": [
                        {"heading": "direct_answer", "content": "BFS 按层扩展，DFS 沿分支深入。", "evidence_ids": ["E1"]},
                        {"heading": "profile_adaptation", "content": "先比较队列与栈。", "evidence_ids": ["E1"]},
                        {"heading": "next_step", "content": "用一个小图手工遍历。", "evidence_ids": ["E1"]},
                    ]
                },
                ensure_ascii=False,
            ),
            metadata={"provider": "fake"},
        )


class OpenAICompatibleHandler(BaseHTTPRequestHandler):
    request_payload: dict | None = None
    auth_header: str | None = None

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        OpenAICompatibleHandler.auth_header = self.headers.get("Authorization")
        OpenAICompatibleHandler.request_payload = json.loads(self.rfile.read(length).decode("utf-8"))
        body = {
            "choices": [
                {
                    "message": {
                        "content": "这是来自本地 fake OpenAI-compatible endpoint 的回答。"
                    }
                }
            ],
            "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
        }
        encoded = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format, *args) -> None:
        return


class OpenAICompatibleErrorHandler(BaseHTTPRequestHandler):
    request_path: str | None = None

    def do_POST(self) -> None:
        OpenAICompatibleErrorHandler.request_path = self.path
        body = {"error": {"message": "Model Not Found", "code": "model_not_found"}}
        encoded = json.dumps(body).encode("utf-8")
        self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format, *args) -> None:
        return


class OpenAICompatibleDisconnectOnceHandler(OpenAICompatibleHandler):
    attempts = 0

    def do_POST(self) -> None:
        OpenAICompatibleDisconnectOnceHandler.attempts += 1
        if OpenAICompatibleDisconnectOnceHandler.attempts == 1:
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()
            return
        super().do_POST()


class OpenAICompatibleSlowHandler(OpenAICompatibleHandler):
    attempts = 0

    def do_POST(self) -> None:
        OpenAICompatibleSlowHandler.attempts += 1
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        time.sleep(0.25)
        encoded = json.dumps({"choices": [{"message": {"content": "slow response"}}]}).encode("utf-8")
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return


class LLMProviderTutorTests(unittest.TestCase):
    def test_tutor_evidence_is_deduplicated_and_bounded(self) -> None:
        chunks = [
            KnowledgeSearchResult(chunk_id=1, content="BFS 使用队列按层遍历。", score=1.0, source_ref="document:1#chunk:1"),
            KnowledgeSearchResult(chunk_id=2, content="  BFS   使用队列按层遍历。 ", score=0.9, source_ref="document:1#chunk:2"),
            KnowledgeSearchResult(chunk_id=3, content="DFS 使用栈沿分支深入。" * 120, score=0.8, source_ref="document:1#chunk:3"),
            KnowledgeSearchResult(chunk_id=4, content="图搜索需要记录访问状态。" * 120, score=0.7, source_ref="document:1#chunk:4"),
            KnowledgeSearchResult(chunk_id=5, content="无关补充。", score=0.1, source_ref="document:1#chunk:5"),
        ]

        selected = select_tutor_evidence(chunks)

        self.assertLessEqual(len(selected), 3)
        self.assertLessEqual(sum(len(item.content) for item in selected), 2400)
        self.assertTrue(all(len(item.content) <= 900 for item in selected))
        self.assertEqual([item.evidence_id for item in selected], [f"E{i}" for i in range(1, len(selected) + 1)])

    def test_tutor_prompt_hides_internal_source_refs_and_maps_evidence_ids(self) -> None:
        provider = PromptCaptureProvider()
        chunk = KnowledgeSearchResult(
            chunk_id=90,
            content="BFS 使用队列，DFS 使用递归或显式栈。",
            score=1.0,
            source_ref="document:9#chunk:0",
        )

        result = LLMBackedTutorAgent(provider).answer("如何区分 BFS 和 DFS？", [chunk])

        prompt = "\n".join(message["content"] for message in provider.messages)
        self.assertIn("E1", prompt)
        self.assertNotIn("document:9#chunk:0", prompt)
        self.assertIn("[document:9#chunk:0]", result.answer)
        self.assertEqual(result.provider_metadata["retrieved_count"], 1)
        self.assertEqual(result.provider_metadata["selected_evidence_count"], 1)
        self.assertEqual(result.provider_metadata["evidence_ids_used"], ["E1"])

    def test_tutor_accepts_schema_json_inside_a_markdown_fence(self) -> None:
        provider = PromptCaptureProvider()
        original_generate = provider.generate

        def fenced_generate(messages, response_schema=None):
            result = original_generate(messages, response_schema)
            return LLMResult(content=f"```json\n{result.content}\n```", metadata=result.metadata)

        provider.generate = fenced_generate
        result = LLMBackedTutorAgent(provider).answer("如何区分 BFS 和 DFS？", [_chunk()])
        self.assertEqual(result.execution_mode, "llm")
        self.assertFalse(result.fallback_used)

    def test_tutor_repairs_only_the_known_flat_section_shape(self) -> None:
        class FlatProvider:
            def generate(self, messages, response_schema=None):
                return LLMResult(content=json.dumps({
                    "direct_answer": "BFS 按层扩展，DFS 沿分支深入。",
                    "profile_adaptation": "先比较队列和栈。",
                    "next_step": "手工遍历一个小图。",
                }, ensure_ascii=False), metadata={"provider": "fake"})

        result = LLMBackedTutorAgent(FlatProvider()).answer("如何区分？", [_chunk()])
        self.assertEqual(result.execution_mode, "llm")
        self.assertEqual(result.provider_metadata["structure_repaired"], "flat_sections")
        self.assertIn("[demo.md#graph-search]", result.answer)

    def test_tutor_fallback_does_not_echo_english_chunk_in_main_answer(self) -> None:
        chunk = KnowledgeSearchResult(
            chunk_id=1,
            content="BFS uses a queue and DFS uses a stack.",
            score=1.0,
            source_ref="document:1#chunk:0",
        )

        result = LLMBackedTutorAgent(FakeProvider(fail=True)).answer("如何区分两种搜索？", [chunk])

        self.assertIn("已切换为安全降级", result.answer)
        self.assertNotIn("BFS uses a queue", result.answer)
        self.assertTrue(result.source_refs)
    def test_openai_compatible_provider_uses_contract_without_exposing_key(self) -> None:
        server = HTTPServer(("127.0.0.1", 0), OpenAICompatibleHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            settings = LLMSettings(
                provider="openai_compatible",
                base_url=f"http://127.0.0.1:{server.server_port}",
                api_key="test-secret",
                model="deepseek-v4-flash",
                timeout_seconds=2,
                max_retries=0,
                max_tokens=321,
                fallback_mode="rule_based",
                enable_for_tutor=True,
                bypass_proxy=True,
            )
            provider = OpenAICompatibleLLMProvider(settings)
            result = provider.generate([{"role": "user", "content": "hello"}])
            unstructured_payload = dict(OpenAICompatibleHandler.request_payload or {})
            provider.generate([{"role": "user", "content": "structured"}], response_schema=dict)
            structured_payload = dict(OpenAICompatibleHandler.request_payload or {})
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertIn("fake OpenAI-compatible", result.content)
        self.assertEqual(result.metadata["provider"], "openai_compatible")
        self.assertEqual(result.metadata["model"], "deepseek-v4-flash")
        self.assertNotIn("test-secret", str(result.metadata))
        self.assertEqual(OpenAICompatibleHandler.auth_header, "Bearer test-secret")
        self.assertEqual(unstructured_payload["model"], "deepseek-v4-flash")
        self.assertEqual(unstructured_payload["max_tokens"], 321)
        self.assertEqual(unstructured_payload["temperature"], 0.2)
        self.assertEqual(result.metadata["retry_count"], 0)
        self.assertGreaterEqual(result.metadata["provider_duration_ms"], 0)
        self.assertEqual(result.metadata["usage"]["total_tokens"], 20)
        self.assertEqual(structured_payload["temperature"], 0.0)

    def test_settings_resolve_a_purpose_specific_budget(self) -> None:
        keys = (
            "LLM_PLANNER_TIMEOUT_SECONDS",
            "LLM_PLANNER_MAX_RETRIES",
            "LLM_PLANNER_MAX_TOKENS",
        )
        previous = {key: os.environ.get(key) for key in keys}
        try:
            os.environ["LLM_PLANNER_TIMEOUT_SECONDS"] = "7"
            os.environ["LLM_PLANNER_MAX_RETRIES"] = "1"
            os.environ["LLM_PLANNER_MAX_TOKENS"] = "456"
            budget = LLMSettings.from_env().budget_for("planner")
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        self.assertEqual(budget.timeout_seconds, 7)
        self.assertEqual(budget.max_retries, 1)
        self.assertEqual(budget.max_tokens, 456)

    def test_timeout_is_not_retried_even_when_retry_budget_is_available(self) -> None:
        OpenAICompatibleSlowHandler.attempts = 0
        server = HTTPServer(("127.0.0.1", 0), OpenAICompatibleSlowHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            settings = LLMSettings(
                provider="openai_compatible",
                base_url=f"http://127.0.0.1:{server.server_port}",
                api_key="test-secret",
                model="test-model",
                timeout_seconds=0.05,
                max_retries=2,
                enable_for_tutor=True,
                bypass_proxy=True,
            )
            with self.assertRaises(LLMProviderError) as context:
                OpenAICompatibleLLMProvider(settings).generate([{"role": "user", "content": "hello"}])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(OpenAICompatibleSlowHandler.attempts, 1)
        self.assertEqual(context.exception.metadata["retry_count"], 0)
        self.assertEqual(context.exception.metadata["purpose"], "tutor")
        self.assertGreaterEqual(context.exception.metadata["provider_duration_ms"], 40)

    def test_provider_error_summary_includes_http_status_and_safe_message(self) -> None:
        server = HTTPServer(("127.0.0.1", 0), OpenAICompatibleErrorHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            settings = LLMSettings(
                provider="openai_compatible",
                base_url=f"http://127.0.0.1:{server.server_port}/chat/completions",
                api_key="test-secret",
                model="wrong-model",
                timeout_seconds=2,
                max_retries=0,
                fallback_mode="rule_based",
                enable_for_tutor=True,
                bypass_proxy=True,
            )
            with self.assertRaises(LLMProviderError) as context:
                OpenAICompatibleLLMProvider(settings).generate([{"role": "user", "content": "hello"}])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        message = str(context.exception)
        self.assertIn("HTTP 404", message)
        self.assertIn("Model Not Found", message)
        self.assertNotIn("test-secret", message)
        self.assertEqual(OpenAICompatibleErrorHandler.request_path, "/chat/completions")

    def test_provider_retries_when_remote_disconnects_before_response(self) -> None:
        OpenAICompatibleDisconnectOnceHandler.attempts = 0
        server = HTTPServer(("127.0.0.1", 0), OpenAICompatibleDisconnectOnceHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            settings = LLMSettings(
                provider="openai_compatible",
                base_url=f"http://127.0.0.1:{server.server_port}",
                api_key="test-secret",
                model="test-model",
                timeout_seconds=2,
                max_retries=1,
                enable_for_tutor=True,
                bypass_proxy=True,
            )
            result = OpenAICompatibleLLMProvider(settings).generate([{"role": "user", "content": "hello"}])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(OpenAICompatibleDisconnectOnceHandler.attempts, 2)
        self.assertIn("fake OpenAI-compatible", result.content)
        self.assertEqual(result.metadata["attempt"], 2)

    def test_llm_tutor_fallback_includes_url_error_reason(self) -> None:
        class UrlErrorProvider:
            def generate(self, messages, response_schema=None) -> LLMResult:
                raise URLError("network unreachable")

        agent = LLMBackedTutorAgent(UrlErrorProvider())
        result = agent.answer("你是谁？", [_chunk()])
        self.assertIn("Fallback reason", result.decision_basis)
        self.assertIn("network unreachable", result.decision_basis)
        self.assertNotIn("Bearer", result.decision_basis)

    def test_tutor_factory_defaults_to_rule_based_without_remote_config(self) -> None:
        agent = build_tutor_agent(LLMSettings(provider="rule_based"))
        self.assertIsInstance(agent, RuleBasedTutorAgent)

    def test_llm_tutor_agent_uses_provider_answer(self) -> None:
        agent = LLMBackedTutorAgent(FakeProvider())
        result = agent.answer("BFS 和 DFS 有什么不同？", [_chunk()])
        self.assertIn("模拟 LLM provider", result.answer)
        self.assertTrue(result.source_refs)
        self.assertIn("E1-E3", result.decision_basis)

    def test_llm_tutor_agent_appends_verified_source_when_provider_omits_inline_citation(self) -> None:
        chunk = KnowledgeSearchResult(
            chunk_id=90,
            content="BFS 使用队列，DFS 使用递归或显式栈。",
            score=1.0,
            source_ref="document:9#chunk:0",
        )
        agent = LLMBackedTutorAgent(FakeProvider())

        result = agent.answer("BFS 和 DFS 使用什么数据结构？", [chunk])
        citation_check = validate_citations(result.answer, result.source_refs)

        self.assertIn("[document:9#chunk:0]", result.answer)
        self.assertFalse(citation_check["missing_citation"])
        self.assertEqual(citation_check["fake_source_refs"], [])
        self.assertNotIn("Fallback reason:", result.decision_basis)

    def test_llm_tutor_agent_falls_back_when_provider_denies_non_empty_context(self) -> None:
        agent = LLMBackedTutorAgent(NoContextProvider())
        result = agent.answer("Why compare BFS and DFS?", [_chunk()])
        self.assertNotIn("No retrieved course chunks", result.answer)
        self.assertTrue(result.source_refs)
        self.assertIn("contradicted non-empty retrieved chunks", result.decision_basis)
        self.assertIn("rule-based", result.output_summary)

    def test_llm_tutor_agent_returns_explicit_limitation_without_retrieved_chunks(self) -> None:
        agent = LLMBackedTutorAgent(UnexpectedCallProvider())

        result = agent.answer("BFS 和 DFS 有什么不同？", [])

        self.assertIn("暂未检索到足够资料", result.answer)
        self.assertEqual(result.source_refs, [])
        self.assertIn("No retrieved course chunks", result.decision_basis)
        self.assertIn("rule-based", result.output_summary)

    def test_llm_tutor_prompt_requires_stable_sections_profile_and_sources(self) -> None:
        provider = PromptCaptureProvider()
        agent = LLMBackedTutorAgent(provider)
        agent.answer("Why compare BFS and DFS?", [_chunk()], "level=beginner; goal=quiz; time_budget=30m")

        system_prompt = provider.messages[0]["content"]
        user_prompt = provider.messages[1]["content"]
        self.assertIn("direct_answer", system_prompt)
        self.assertIn("profile_adaptation", system_prompt)
        self.assertIn("next_step", system_prompt)
        self.assertIn("简体中文", system_prompt)
        self.assertIn("禁止输出 document:*", system_prompt)
        self.assertIn("level=beginner", user_prompt)
        self.assertIn("E1:", user_prompt)
        self.assertNotIn("demo.md#graph-search", user_prompt)

    def test_tutor_prompt_caps_each_retrieved_chunk_to_keep_latency_bounded(self) -> None:
        provider = PromptCaptureProvider()
        long_marker = "不应完整进入提示词"
        chunk = KnowledgeSearchResult(
            chunk_id=2,
            content="BFS 使用队列。" + ("图搜索证据" * 300) + long_marker,
            score=1.0,
            source_ref="document:2#chunk:0",
        )

        LLMBackedTutorAgent(provider).answer("如何区分 BFS 和 DFS？", [chunk])

        user_prompt = provider.messages[1]["content"]
        self.assertNotIn(long_marker, user_prompt)
        self.assertLess(len(user_prompt), 1800)

    def test_llm_tutor_agent_falls_back_when_provider_fails(self) -> None:
        agent = LLMBackedTutorAgent(FakeProvider(fail=True))
        result = agent.answer("复杂度分析有什么用？", [_chunk()])
        self.assertIn("已切换为安全降级", result.answer)
        self.assertIn("Fallback reason", result.decision_basis)
        self.assertIn("rule-based", result.output_summary)

    def test_llm_tutor_agent_raises_when_fallback_mode_is_error(self) -> None:
        agent = LLMBackedTutorAgent(FakeProvider(fail=True), fallback_mode="error")
        with self.assertRaises(LLMProviderError) as context:
            agent.answer("复杂度分析有什么用？", [_chunk()])

        self.assertIn("provider unavailable", str(context.exception))

    def test_tutor_api_records_fallback_step_when_provider_fails(self) -> None:
        server = HTTPServer(("127.0.0.1", 0), OpenAICompatibleErrorHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(temp_dir.name) / "llm-fallback-api-test.sqlite3"
        database_url = f"sqlite:///{database_path.as_posix()}"
        env_keys = [
            "APP_DATABASE_URL",
            "LLM_PROVIDER",
            "LLM_BASE_URL",
            "LLM_API_KEY",
            "LLM_MODEL",
            "LLM_TIMEOUT_SECONDS",
            "LLM_MAX_RETRIES",
            "LLM_FALLBACK_MODE",
            "LLM_ENABLE_FOR_TUTOR",
            "LLM_BYPASS_PROXY",
        ]
        previous_env = {key: os.environ.get(key) for key in env_keys}
        try:
            os.environ["APP_DATABASE_URL"] = database_url
            os.environ["LLM_PROVIDER"] = "openai_compatible"
            os.environ["LLM_BASE_URL"] = f"http://127.0.0.1:{server.server_port}"
            os.environ["LLM_API_KEY"] = "integration-secret"
            os.environ["LLM_MODEL"] = "deepseek-v4-flash"
            os.environ["LLM_TIMEOUT_SECONDS"] = "2"
            os.environ["LLM_MAX_RETRIES"] = "0"
            os.environ["LLM_FALLBACK_MODE"] = "rule_based"
            os.environ["LLM_ENABLE_FOR_TUTOR"] = "true"
            os.environ["LLM_BYPASS_PROXY"] = "true"

            with TestClient(create_app()) as client:
                demo = client.post("/api/v1/demo-data/load").json()["demo_data"]
                profile = client.get("/api/v1/student-profiles").json()[0]
                tutor = client.post(
                    "/api/v1/tutor/ask",
                    json={
                        "student_profile_id": profile["id"],
                        "course_id": demo["course_id"],
                        "question": "复杂度分析有什么用？",
                    },
                )

                self.assertEqual(tutor.status_code, 200)
                tutor_body = tutor.json()
                self.assertEqual(
                    set(tutor_body.keys()),
                    {
                        "answer",
                        "source_refs",
                        "agent_run_id",
                        "safety_status",
                        "safety_message",
                        "postprocessing_task_id",
                        "postprocessing_status",
                    },
                )
                self.assertEqual(tutor_body["safety_status"], "degraded")
                self.assertIn("已切换为安全降级", tutor_body["answer"])
                self.assertTrue(tutor_body["source_refs"])

                run = client.get(f"/api/v1/agent-runs/{tutor_body['agent_run_id']}")
                self.assertEqual(run.status_code, 200)
                run_body = run.json()
                self.assertEqual(run_body["status"], "completed")
                tutor_step = next(step for step in run_body["steps"] if step["agent_type"] == "tutor")
                self.assertIn("回退到 rule-based", tutor_step["output_summary"])
                self.assertIn("Fallback reason", tutor_step["decision_basis"])
                self.assertIn("HTTP 404", tutor_step["decision_basis"])
                self.assertEqual(tutor_step["execution_metadata"]["execution_mode"], "rule_based_fallback")
                self.assertEqual(tutor_step["execution_metadata"]["provider"], "openai_compatible")
                self.assertEqual(tutor_step["execution_metadata"]["model"], "deepseek-v4-flash")
                self.assertTrue(tutor_step["execution_metadata"]["fallback_used"])
                self.assertIn("HTTP 404", tutor_step["execution_metadata"]["fallback_reason"])
                self.assertTrue(tutor_step["execution_metadata"]["source_refs"])
                self.assertGreater(tutor_step["execution_metadata"]["retrieved_count"], 0)
                self.assertLessEqual(tutor_step["execution_metadata"]["selected_evidence_count"], 3)
                self.assertLessEqual(tutor_step["execution_metadata"]["context_chars"], 2400)
                self.assertNotIn("integration-secret", json.dumps(run_body, ensure_ascii=False))
        finally:
            get_engine().dispose()
            get_engine(database_url).dispose()
            get_engine.cache_clear()
            for key, value in previous_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            temp_dir.cleanup()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


def _chunk() -> KnowledgeSearchResult:
    return KnowledgeSearchResult(
        chunk_id=1,
        content="BFS 适合按层遍历，DFS 适合沿路径深入搜索。",
        score=1.0,
        source_ref="demo.md#graph-search",
        metadata={"concept_slug": "bfs-dfs"},
    )


if __name__ == "__main__":
    unittest.main()
