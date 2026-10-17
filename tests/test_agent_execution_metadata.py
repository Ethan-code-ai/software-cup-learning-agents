import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import inspect, text

from app.db.schema_compat import ensure_agent_run_step_columns
from app.db.session import get_engine
from app.schemas import AgentExecutionMetadata
from app.services.agent_execution_metadata import build_execution_metadata
from app.services.agent_run_service import AgentRunService
from app.services.demo_data_service import DemoDataService
from app.services.profile_service import ProfileService

REPO_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_APP = REPO_ROOT / "src" / "frontend" / "src" / "App.tsx"
FRONTEND_TYPES = REPO_ROOT / "src" / "frontend" / "src" / "api" / "types.ts"


class AgentExecutionMetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "agent-execution-metadata.sqlite3"
        self.database_url = f"sqlite:///{self.database_path.as_posix()}"

    def tearDown(self) -> None:
        get_engine(self.database_url).dispose()
        get_engine.cache_clear()
        os.environ.pop("LLM_API_KEY", None)
        self.temp_dir.cleanup()

    def test_metadata_normalizes_fallback_mode_and_keeps_only_source_identifiers(self) -> None:
        result = SimpleNamespace(
            execution_mode="rule_based_critic_fallback",
            provider="openai_compatible",
            model="xop3qwen1b7",
            fallback_used=True,
            fallback_reason="Critic rejected unsafe output.",
            duration_ms=321,
            source_refs=[
                {
                    "source_ref": "document:9#chunk:2",
                    "content": "full retrieved content must not be persisted",
                    "excerpt": "private excerpt",
                }
            ],
            provider_metadata={
                "provider_duration_ms": 287,
                "retry_count": 1,
                "usage": {
                    "prompt_tokens": 120,
                    "completion_tokens": 30,
                    "total_tokens": 150,
                    "raw_secret": "must not persist",
                },
            },
        )

        metadata = build_execution_metadata(result)

        self.assertEqual(metadata["execution_mode"], "rule_based_fallback")
        self.assertEqual(metadata["provider"], "openai_compatible")
        self.assertEqual(metadata["model"], "xop3qwen1b7")
        self.assertTrue(metadata["fallback_used"])
        self.assertEqual(metadata["source_refs"], ["document:9#chunk:2"])
        self.assertEqual(metadata["duration_ms"], 321)
        self.assertEqual(metadata["provider_duration_ms"], 287)
        self.assertEqual(metadata["retry_count"], 1)
        self.assertEqual(metadata["token_usage"], {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150})
        serialized = json.dumps(metadata, ensure_ascii=False)
        self.assertNotIn("full retrieved content", serialized)
        self.assertNotIn("private excerpt", serialized)
        self.assertNotIn("raw_secret", serialized)
        self.assertNotIn("must not persist", serialized)

    def test_metadata_redacts_process_secrets_and_ignores_unknown_fields(self) -> None:
        os.environ["LLM_API_KEY"] = "trace-test-super-secret"

        metadata = build_execution_metadata(
            execution_mode="rule_based_fallback",
            provider="openai_compatible",
            model="test-model",
            fallback_used=True,
            fallback_reason=(
                "HTTP 401 api_key=trace-test-super-secret; "
                "Authorization: Bearer another-sensitive-token"
            ),
            duration_ms=12,
            source_refs=["document:1#chunk:2?api_key=trace-test-super-secret"],
            prompt="full prompt must be ignored",
            api_key="must-not-be-persisted",
        )

        serialized = json.dumps(metadata, ensure_ascii=False)
        self.assertNotIn("trace-test-super-secret", serialized)
        self.assertNotIn("another-sensitive-token", serialized)
        self.assertNotIn("full prompt", serialized)
        self.assertNotIn("must-not-be-persisted", serialized)
        self.assertIn("[REDACTED]", metadata["fallback_reason"])
        self.assertNotIn("trace-test-super-secret", metadata["source_refs"][0])

    def test_agent_run_api_persists_additive_structured_metadata(self) -> None:
        os.environ["LLM_API_KEY"] = "trace-test-super-secret"
        demo = DemoDataService(database_url=self.database_url).load_demo_data().demo_data
        profile_id = ProfileService(database_url=self.database_url).list_demo_profiles()[0].id
        service = AgentRunService(database_url=self.database_url)
        run = service.start_run("metadata_test", profile_id, demo.course_id, "safe summary")

        recorded = service.record_step(
            run.id,
            "tutor",
            "safe input summary",
            "safe output summary",
            "HTTP 401 api_key=trace-test-super-secret",
            "completed",
            execution_metadata={
                "execution_mode": "llm",
                "provider": "openai_compatible",
                "model": "xop3qwen1b7",
                "fallback_used": False,
                "fallback_reason": None,
                "source_refs": ["document:1#chunk:2"],
                "duration_ms": 88,
            },
        )
        fetched = service.get_run(run.id).steps[0]

        expected = AgentExecutionMetadata(
            execution_mode="llm",
            provider="openai_compatible",
            model="xop3qwen1b7",
            source_refs=["document:1#chunk:2"],
            duration_ms=88,
        )
        self.assertEqual(recorded.execution_metadata, expected)
        self.assertEqual(fetched.execution_metadata, expected)
        self.assertEqual(fetched.duration_ms, 88)
        self.assertNotIn("trace-test-super-secret", fetched.decision_basis)
        self.assertIn("[REDACTED]", fetched.decision_basis)

    def test_schema_compat_adds_metadata_column_to_an_existing_sqlite_table(self) -> None:
        engine = get_engine(self.database_url)
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE agent_run_steps (
                        id INTEGER PRIMARY KEY,
                        agent_run_id INTEGER NOT NULL,
                        agent_type VARCHAR(80) NOT NULL,
                        step_order INTEGER NOT NULL,
                        status VARCHAR(40) NOT NULL,
                        input_summary TEXT NOT NULL,
                        output_summary TEXT NOT NULL,
                        decision_basis TEXT NOT NULL,
                        duration_ms INTEGER,
                        error TEXT
                    )
                    """
                )
            )

        ensure_agent_run_step_columns(self.database_url)

        columns = {column["name"] for column in inspect(engine).get_columns("agent_run_steps")}
        self.assertIn("execution_metadata", columns)

    def test_frontend_keeps_runtime_trace_scoped_and_typed(self) -> None:
        trace = (FRONTEND_APP.parent / "components" / "AgentTrace.tsx").read_text(encoding="utf-8")
        types = FRONTEND_TYPES.read_text(encoding="utf-8")

        self.assertIn("const traceRunTypes", trace)
        for run_type in (
            "profile_build",
            "profile_update",
            "learning_path_planning",
            "learning_path_replanning",
            "resource_generation",
            "tutor_answer",
            "quiz_generation",
            "attempt_evaluation",
        ):
            self.assertIn(f'"{run_type}"', trace)
        self.assertIn("export interface AgentExecutionMetadata", types)
        self.assertIn("execution_metadata: AgentExecutionMetadata", types)


if __name__ == "__main__":
    unittest.main()
