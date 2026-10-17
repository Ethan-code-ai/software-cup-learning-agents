import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_SCRIPT = REPO_ROOT / "scripts" / "report-llm-performance.py"


def load_report_module():
    spec = importlib.util.spec_from_file_location("report_llm_performance", REPORT_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load performance report script.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PerformanceObservabilityTests(unittest.TestCase):
    def test_api_response_exposes_bounded_request_timing_without_request_content(self) -> None:
        with TestClient(create_app()) as client:
            response = client.get("/openapi.json", headers={"X-Request-ID": "perf-test-request"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Request-ID"], "perf-test-request")
        self.assertGreaterEqual(int(response.headers["X-Process-Time-Ms"]), 0)
        self.assertEqual(response.headers["Server-Timing"], f"app;dur={response.headers['X-Process-Time-Ms']}")

        with TestClient(create_app()) as client:
            unsafe = client.get("/openapi.json", headers={"X-Request-ID": "unsafe log-entry"})
        self.assertNotEqual(unsafe.headers["X-Request-ID"], "unsafe log-entry")
        self.assertRegex(unsafe.headers["X-Request-ID"], r"^[a-f0-9]{32}$")

    def test_report_calculates_nearest_rank_percentiles_and_safe_aggregates(self) -> None:
        module = load_report_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "performance.sqlite3"
            connection = sqlite3.connect(database_path)
            try:
                connection.execute(
                    "CREATE TABLE agent_run_steps (id INTEGER PRIMARY KEY, agent_type TEXT, duration_ms INTEGER, execution_metadata TEXT)"
                )
                for index, duration in enumerate((100, 200, 300, 400), start=1):
                    metadata = {
                        "execution_mode": "rule_based_fallback" if index == 4 else "llm",
                        "provider": "openai_compatible",
                        "provider_duration_ms": duration - 10,
                        "retry_count": 1 if index == 4 else 0,
                        "token_usage": {"total_tokens": 10 * index},
                        "fallback_used": index == 4,
                        "fallback_reason": "timeout" if index == 4 else None,
                    }
                    connection.execute(
                        "INSERT INTO agent_run_steps VALUES (?, ?, ?, ?)",
                        (index, "planner", duration, json.dumps(metadata)),
                    )
                connection.commit()
            finally:
                connection.close()

            report = module.build_report(database_path)

        planner = report["agents"]["planner"]
        self.assertEqual(planner["duration_ms"], {"p50": 200, "p95": 400})
        self.assertEqual(planner["provider_duration_ms"], {"p50": 190, "p95": 390})
        self.assertEqual(planner["retry_count"], 1)
        self.assertEqual(planner["total_tokens"], 100)
        self.assertEqual(planner["fallback_count"], 1)
        self.assertEqual(planner["fallback_reasons"], ["timeout"])


if __name__ == "__main__":
    unittest.main()
