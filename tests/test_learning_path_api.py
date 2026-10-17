import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.db.session import get_engine
from app.main import create_app


class LearningPathApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "learning-path-test.sqlite3"
        self.database_url = f"sqlite:///{self.database_path.as_posix()}"
        os.environ["APP_DATABASE_URL"] = self.database_url

    def tearDown(self) -> None:
        get_engine().dispose()
        get_engine(self.database_url).dispose()
        get_engine.cache_clear()
        os.environ.pop("APP_DATABASE_URL", None)
        self.temp_dir.cleanup()

    def test_learning_path_creation_runs_planner_and_records_agent_step(self) -> None:
        with TestClient(create_app()) as client:
            status_response = client.post("/api/v1/demo-data/load")
            demo_status = status_response.json()["demo_data"]
            profile = client.get("/api/v1/student-profiles").json()[0]

            payload = {
                "student_profile_id": profile["id"],
                "course_id": demo_status["course_id"],
                "goal": "我想复习树和二叉树，准备小测",
            }
            response = client.post("/api/v1/learning-paths", json=payload)
            self.assertEqual(response.status_code, 200)
            body = response.json()

            path = body["learning_path"]
            self.assertEqual(path["student_profile_id"], payload["student_profile_id"])
            self.assertEqual(path["course_id"], payload["course_id"])
            self.assertEqual(path["goal"], payload["goal"])
            self.assertEqual(path["status"], "active")
            self.assertIn("Planner Agent", path["rationale"])
            self.assertLessEqual(len(path["items"]), 8)
            self.assertGreaterEqual(len(path["items"]), 2)

            concept_ids = [item["concept_id"] for item in path["items"]]
            self.assertEqual(len(concept_ids), len(set(concept_ids)))
            self.assertEqual([item["order_index"] for item in path["items"]], list(range(1, len(path["items"]) + 1)))
            titles = " ".join(item["title"] for item in path["items"])
            self.assertIn("树", titles)
            self.assertIn("二叉树", titles)
            self.assertNotIn("排序", titles)
            for item in path["items"]:
                self.assertTrue(item["title"])
                self.assertTrue(item["objective"])
                self.assertTrue(item["rationale"])

            run = body["agent_run"]
            self.assertEqual(run["run_type"], "learning_path_planning")
            self.assertEqual(run["student_profile_id"], payload["student_profile_id"])
            self.assertEqual(run["course_id"], payload["course_id"])
            self.assertEqual(run["status"], "completed")
            self.assertTrue(run["final_summary"])
            self.assertEqual(run["steps"][0]["agent_type"], "router")
            planner_steps = [step for step in run["steps"] if step["agent_type"] == "planner"]
            self.assertEqual(len(planner_steps), 3)
            self.assertIn("phase=goal_resolution", planner_steps[0]["decision_basis"])
            planner_step = next(step for step in run["steps"] if step["agent_type"] == "planner")
            self.assertEqual(planner_step["status"], "completed")
            self.assertTrue(planner_step["input_summary"])
            self.assertTrue(planner_step["output_summary"])
            self.assertTrue(planner_step["decision_basis"])

            path_detail = client.get(f"/api/v1/learning-paths/{path['id']}")
            self.assertEqual(path_detail.status_code, 200)
            self.assertEqual(path_detail.json()["id"], path["id"])

            run_detail = client.get(f"/api/v1/agent-runs/{run['id']}")
            self.assertEqual(run_detail.status_code, 200)
            self.assertIn("planner", [step["agent_type"] for step in run_detail.json()["steps"]])

    def test_learning_path_missing_inputs_return_404(self) -> None:
        with TestClient(create_app()) as client:
            response = client.post(
                "/api/v1/learning-paths",
                json={
                    "student_profile_id": 999999,
                    "course_id": 999999,
                    "goal": "不存在的输入",
                },
            )
            self.assertEqual(response.status_code, 404)

            path_response = client.get("/api/v1/learning-paths/999999")
            self.assertEqual(path_response.status_code, 404)

            run_response = client.get("/api/v1/agent-runs/999999")
            self.assertEqual(run_response.status_code, 404)
