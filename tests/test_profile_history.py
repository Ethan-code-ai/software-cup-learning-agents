import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.session import get_engine, get_session_factory
from app.main import create_app
from app.models import LearningPath, StudentProfileHistory


class ProfileHistoryApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "profile-history.sqlite3"
        self.database_url = f"sqlite:///{self.database_path.as_posix()}"
        os.environ["APP_DATABASE_URL"] = self.database_url

    def tearDown(self) -> None:
        get_engine().dispose()
        get_engine(self.database_url).dispose()
        get_engine.cache_clear()
        os.environ.pop("APP_DATABASE_URL", None)
        self.temp_dir.cleanup()

    def test_dialogue_profile_records_six_dimension_initial_snapshot(self) -> None:
        with TestClient(create_app()) as client:
            dialogue = "我基础薄弱，想用例题和代码学习链表，每天 1 小时。"
            profile = client.post(
                "/api/v1/student-profiles/from-dialogue",
                json={"dialogue": dialogue},
            ).json()

            response = client.get(f"/api/v1/student-profiles/{profile['id']}/history")
            self.assertEqual(response.status_code, 200)
            history = response.json()
            self.assertEqual(len(history), 1)
            record = history[0]
            self.assertEqual(record["trigger_type"], "dialogue")
            self.assertEqual(record["before_dimensions"], {})
            self.assertEqual(
                set(record["after_dimensions"]),
                {
                    "learning_goal",
                    "foundation_level",
                    "learning_preference",
                    "available_time",
                    "weak_points",
                    "resource_preference",
                },
            )
            self.assertNotIn(dialogue, record["reason"])
            self.assertTrue(record["evidence_refs"])

    def test_manual_sync_without_new_evidence_is_a_noop(self) -> None:
        with TestClient(create_app()) as client:
            profile = client.post(
                "/api/v1/student-profiles/from-dialogue",
                json={"dialogue": "我想学习图搜索，每天 1 小时。"},
            ).json()
            before = client.get(f"/api/v1/student-profiles/{profile['id']}/history").json()

            response = client.post(f"/api/v1/student-profiles/{profile['id']}/update-from-trace")
            self.assertEqual(response.status_code, 200)
            after = client.get(f"/api/v1/student-profiles/{profile['id']}/history").json()
            self.assertEqual(len(after), len(before))

    def test_quiz_evaluation_creates_traceable_profile_history(self) -> None:
        with TestClient(create_app()) as client:
            demo = client.post("/api/v1/demo-data/load").json()["demo_data"]
            profiles = client.get("/api/v1/student-profiles").json()
            profile = next(item for item in profiles if item["profile_type"] == "exam_sprint")
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
                json={"student_profile_id": profile["id"], "answers": {"answer": "完全不会"}},
            )
            self.assertEqual(attempt.status_code, 200)

            history = client.get(f"/api/v1/student-profiles/{profile['id']}/history").json()
            quiz_records = [item for item in history if item["trigger_type"] == "quiz"]
            self.assertEqual(len(quiz_records), 1)
            self.assertIn("foundation_level", quiz_records[0]["changed_dimensions"])
            self.assertEqual(quiz_records[0]["agent_run_id"], attempt.json()["agent_run_id"])

    def test_history_is_idempotent_for_same_event_key(self) -> None:
        with TestClient(create_app()) as client:
            profile = client.post(
                "/api/v1/student-profiles/from-dialogue",
                json={"dialogue": "我希望通过代码练习栈和队列。"},
            ).json()
            history = client.get(f"/api/v1/student-profiles/{profile['id']}/history").json()
            self.assertEqual(len(history), 1)

            session = get_session_factory(self.database_url)()
            try:
                records = session.scalars(
                    select(StudentProfileHistory).where(StudentProfileHistory.student_profile_id == profile["id"])
                ).all()
                self.assertEqual(len(records), 1)
                self.assertTrue(records[0].event_key)
            finally:
                session.close()

    def test_path_item_completion_updates_state_and_rejects_duplicates(self) -> None:
        with TestClient(create_app()) as client:
            demo = client.post("/api/v1/demo-data/load").json()["demo_data"]
            profile = client.get("/api/v1/student-profiles").json()[0]
            flow = client.post("/api/v1/learning-paths", json={
                "student_profile_id": profile["id"], "course_id": demo["course_id"], "goal": "系统掌握整门课程"
            }).json()
            item_id = flow["learning_path"]["items"][0]["id"]
            completed = client.post(f"/api/v1/learning-path-items/{item_id}/complete")
            self.assertEqual(completed.status_code, 200)
            self.assertEqual(completed.json()["items"][0]["status"], "completed")
            self.assertEqual(completed.json()["items"][1]["status"], "in_progress")
            duplicate = client.post(f"/api/v1/learning-path-items/{item_id}/complete")
            self.assertEqual(duplicate.status_code, 409)

    def test_path_item_completion_survives_legacy_goal_replanning_failure(self) -> None:
        with TestClient(create_app()) as client:
            demo = client.post("/api/v1/demo-data/load").json()["demo_data"]
            profile = client.get("/api/v1/student-profiles").json()[0]
            flow = client.post("/api/v1/learning-paths", json={
                "student_profile_id": profile["id"], "course_id": demo["course_id"], "goal": "系统掌握整门课程"
            }).json()
            path_id = flow["learning_path"]["id"]
            item_id = flow["learning_path"]["items"][0]["id"]

            session = get_session_factory(self.database_url)()
            try:
                path = session.get(LearningPath, path_id)
                path.goal = "把这个再弄扎实一点"
                path.learning_intent = {}
                path.target_concept_ids = []
                session.commit()
            finally:
                session.close()

            completed = client.post(f"/api/v1/learning-path-items/{item_id}/complete")
            self.assertEqual(completed.status_code, 200)
            self.assertEqual(completed.json()["items"][0]["status"], "completed")
            self.assertEqual(completed.json()["items"][1]["status"], "in_progress")


if __name__ == "__main__":
    unittest.main()
