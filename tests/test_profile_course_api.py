import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.db.session import get_engine
from app.main import create_app
from app.seed.demo_data import DEMO_CONCEPTS, DEMO_PROFILES, DEMO_RELATIONS


PROFILE_DIMENSION_KEYS = {
    "learning_goal",
    "foundation_level",
    "learning_preference",
    "available_time",
    "weak_points",
    "resource_preference",
}


class ProfileCourseApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "api-test.sqlite3"
        self.database_url = f"sqlite:///{self.database_path.as_posix()}"
        os.environ["APP_DATABASE_URL"] = self.database_url

    def tearDown(self) -> None:
        get_engine().dispose()
        get_engine(self.database_url).dispose()
        get_engine.cache_clear()
        os.environ.pop("APP_DATABASE_URL", None)
        self.temp_dir.cleanup()

    def test_student_profile_list_and_detail_return_demo_profiles(self) -> None:
        with TestClient(create_app()) as client:
            response = client.get("/api/v1/student-profiles")
            self.assertEqual(response.status_code, 200)
            profiles = response.json()

            self.assertEqual(len(profiles), len(DEMO_PROFILES))
            self.assertEqual(
                {profile["profile_type"] for profile in profiles},
                {str(profile["profile_type"]) for profile in DEMO_PROFILES},
            )
            for profile in profiles:
                self.assertTrue(profile["goal"])
                self.assertTrue(profile["level"])
                self.assertTrue(profile["preferences"])
                self.assertTrue(profile["time_budget"])
                self.assertTrue(PROFILE_DIMENSION_KEYS.issubset(set(profile["preferences"])))

            detail = client.get(f"/api/v1/student-profiles/{profiles[0]['id']}")
            self.assertEqual(detail.status_code, 200)
            self.assertEqual(detail.json()["id"], profiles[0]["id"])

    def test_student_profile_create_returns_created_profile(self) -> None:
        payload = {
            "profile_type": "weak_foundation",
            "goal": "重点复习链表和栈队列",
            "level": "beginner",
            "preferences": {"style": "worked_examples"},
            "time_budget": "每天 45 分钟",
        }
        with TestClient(create_app()) as client:
            response = client.post("/api/v1/student-profiles", json=payload)
            self.assertEqual(response.status_code, 200)
            created = response.json()
            self.assertGreater(created["id"], 0)
            self.assertEqual(created["goal"], payload["goal"])
            self.assertEqual(created["preferences"]["style"], payload["preferences"]["style"])
            self.assertTrue(PROFILE_DIMENSION_KEYS.issubset(set(created["preferences"])))

    def test_student_profile_create_from_dialogue_returns_six_dimension_profile(self) -> None:
        payload = {
            "dialogue": "我基础薄弱，想每天 1 小时复习二叉树遍历和 BFS/DFS，希望用例题和练习题准备小测"
        }
        with TestClient(create_app()) as client:
            response = client.post("/api/v1/student-profiles/from-dialogue", json=payload)
            self.assertEqual(response.status_code, 200)
            created = response.json()

            self.assertGreater(created["id"], 0)
            self.assertEqual(created["profile_type"], "exam_sprint")
            self.assertEqual(created["level"], "beginner")
            self.assertIn("二叉树遍历", created["preferences"]["weak_points"])
            self.assertIn("BFS/DFS", created["preferences"]["weak_points"])
            self.assertTrue(PROFILE_DIMENSION_KEYS.issubset(set(created["preferences"])))

            status_response = client.post("/api/v1/demo-data/load")
            course_id = status_response.json()["demo_data"]["course_id"]
            path_response = client.post(
                "/api/v1/learning-paths",
                json={
                    "student_profile_id": created["id"],
                    "course_id": course_id,
                    "goal": created["goal"],
                },
            )
            self.assertEqual(path_response.status_code, 200)
            self.assertEqual(path_response.json()["learning_path"]["student_profile_id"], created["id"])

    def test_user_profile_can_be_deleted_but_demo_profile_is_protected(self) -> None:
        with TestClient(create_app()) as client:
            profiles = client.get("/api/v1/student-profiles").json()
            demo_delete = client.delete(f"/api/v1/student-profiles/{profiles[0]['id']}")
            self.assertEqual(demo_delete.status_code, 409)

            created = client.post(
                "/api/v1/student-profiles/from-dialogue",
                json={"dialogue": "我想用代码练习链表，每周 6 小时。"},
            ).json()
            self.assertEqual(created["preferences"]["profile_origin"], "user_dialogue")
            delete_response = client.delete(f"/api/v1/student-profiles/{created['id']}")
            self.assertEqual(delete_response.status_code, 204)

            missing = client.get(f"/api/v1/student-profiles/{created['id']}")
            self.assertEqual(missing.status_code, 404)

            remaining_profiles = client.get("/api/v1/student-profiles").json()
            self.assertEqual(len(remaining_profiles), len(DEMO_PROFILES))

    def test_course_graph_returns_demo_course_concepts_and_relations(self) -> None:
        with TestClient(create_app()) as client:
            status_response = client.post("/api/v1/demo-data/load")
            self.assertEqual(status_response.status_code, 200)
            course_id = status_response.json()["demo_data"]["course_id"]

            graph_response = client.get(f"/api/v1/courses/{course_id}/graph")
            self.assertEqual(graph_response.status_code, 200)
            graph = graph_response.json()

            self.assertEqual(graph["course_title"], "数据结构")
            self.assertEqual(len(graph["concepts"]), len(DEMO_CONCEPTS))
            self.assertEqual(len(graph["relations"]), len(DEMO_RELATIONS))
            self.assertEqual(
                {concept["slug"] for concept in graph["concepts"]},
                {concept["slug"] for concept in DEMO_CONCEPTS},
            )
            for concept in graph["concepts"]:
                self.assertIn("chapter", concept)
                self.assertTrue(concept["name"])
                self.assertTrue(concept["difficulty"])

    def test_missing_profile_and_course_return_404(self) -> None:
        with TestClient(create_app()) as client:
            profile_response = client.get("/api/v1/student-profiles/999999")
            self.assertEqual(profile_response.status_code, 404)

            course_response = client.get("/api/v1/courses/999999/graph")
            self.assertEqual(course_response.status_code, 404)
