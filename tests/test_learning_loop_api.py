import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.db.session import get_engine
from app.main import create_app


RESOURCE_TYPES = [
    "guided_note",
    "practice_questions",
    "mind_map",
    "extended_reading",
    "coding_case",
]


class LearningLoopApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "learning-loop-test.sqlite3"
        self.database_url = f"sqlite:///{self.database_path.as_posix()}"
        os.environ["APP_DATABASE_URL"] = self.database_url

    def tearDown(self) -> None:
        get_engine().dispose()
        get_engine(self.database_url).dispose()
        get_engine.cache_clear()
        os.environ.pop("APP_DATABASE_URL", None)
        self.temp_dir.cleanup()

    def test_resource_tutor_quiz_evaluator_minimum_loop_records_agent_steps(self) -> None:
        with TestClient(create_app()) as client:
            demo = client.post("/api/v1/demo-data/load").json()["demo_data"]
            profile = client.get("/api/v1/student-profiles").json()[0]
            graph = client.get(f"/api/v1/courses/{demo['course_id']}/graph").json()

            learning_flow = client.post(
                "/api/v1/learning-paths",
                json={
                    "student_profile_id": profile["id"],
                    "course_id": demo["course_id"],
                    "goal": "准备 BFS/DFS 课程小测",
                },
            ).json()
            path_item = learning_flow["learning_path"]["items"][0]

            resource = client.post(
                "/api/v1/resources/generate",
                json={"path_item_id": path_item["id"], "resource_type": "讲义"},
            )
            self.assertEqual(resource.status_code, 200)
            resource_body = resource.json()
            self.assertEqual(resource_body["path_item_id"], path_item["id"])
            self.assertTrue(resource_body["content"])
            self.assertTrue(resource_body["source_refs"])
            self.assertIsNotNone(resource_body["agent_run_id"])

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
            self.assertTrue(tutor_body["answer"])
            self.assertTrue(tutor_body["source_refs"])
            self.assertIsNotNone(tutor_body["agent_run_id"])

            concept_id = graph["concepts"][0]["id"]
            quiz = client.post(
                "/api/v1/quizzes/generate",
                json={"student_profile_id": profile["id"], "concept_id": concept_id, "difficulty": "basic"},
            )
            self.assertEqual(quiz.status_code, 200)
            quiz_body = quiz.json()
            self.assertEqual(quiz_body["concept_id"], concept_id)
            self.assertEqual(quiz_body["difficulty"], "basic")
            self.assertTrue(quiz_body["items"])
            self.assertTrue(quiz_body["items"][0]["answer"])
            self.assertTrue(quiz_body["items"][0]["explanation"])
            self.assertTrue(quiz_body["items"][0]["concept_tags"])
            self.assertIsNotNone(quiz_body["agent_run_id"])

            attempt = client.post(
                f"/api/v1/quizzes/{quiz_body['id']}/attempts",
                json={"student_profile_id": profile["id"], "answers": {"answer": quiz_body["items"][0]["answer"]}},
            )
            self.assertEqual(attempt.status_code, 200)
            attempt_body = attempt.json()
            self.assertGreaterEqual(attempt_body["score"], 0.0)
            self.assertTrue(attempt_body["feedback"])
            self.assertTrue(attempt_body["mastery_updates"])
            self.assertIsNotNone(attempt_body["agent_run_id"])

            agent_run_ids = [
                resource_body["agent_run_id"],
                tutor_body["agent_run_id"],
                quiz_body["agent_run_id"],
                attempt_body["agent_run_id"],
            ]
            expected_agents = ["resource", "tutor", "quiz", "evaluator"]
            for run_id, expected_agent in zip(agent_run_ids, expected_agents, strict=True):
                run = client.get(f"/api/v1/agent-runs/{run_id}")
                self.assertEqual(run.status_code, 200)
                run_body = run.json()
                self.assertEqual(run_body["status"], "completed")
                step = next(step for step in run_body["steps"] if step["agent_type"] == expected_agent)
                self.assertTrue(step["input_summary"])
                self.assertTrue(step["output_summary"])
                self.assertTrue(step["decision_basis"])

            profile_update = client.post(f"/api/v1/student-profiles/{profile['id']}/update-from-trace")
            self.assertEqual(profile_update.status_code, 200)
            updated_profile = profile_update.json()
            preferences = updated_profile["preferences"]
            self.assertIn("last_profile_update_reason", preferences)
            self.assertIn("last_profile_update_sources", preferences)
            self.assertTrue(preferences["last_profile_update_sources"])
            self.assertIn("Agent step", preferences["last_profile_update_reason"])

    def test_resource_agent_generates_five_competition_resource_types(self) -> None:
        with TestClient(create_app()) as client:
            demo = client.post("/api/v1/demo-data/load").json()["demo_data"]
            profile = client.get("/api/v1/student-profiles").json()[0]
            learning_flow = client.post(
                "/api/v1/learning-paths",
                json={
                    "student_profile_id": profile["id"],
                    "course_id": demo["course_id"],
                    "goal": "准备 BFS/DFS 课程小测",
                },
            ).json()
            path_item = learning_flow["learning_path"]["items"][0]

            for resource_type in RESOURCE_TYPES:
                response = client.post(
                    "/api/v1/resources/generate",
                    json={"path_item_id": path_item["id"], "resource_type": resource_type},
                )
                self.assertEqual(response.status_code, 200)
                body = response.json()
                self.assertEqual(body["path_item_id"], path_item["id"])
                self.assertEqual(body["resource_type"], resource_type)
                self.assertIn(path_item["objective"], body["content"])
                self.assertTrue(body["source_refs"])
                self.assertIsNotNone(body["agent_run_id"])

    def test_teaching_video_returns_validated_animation_spec(self) -> None:
        with TestClient(create_app()) as client:
            demo = client.post("/api/v1/demo-data/load").json()["demo_data"]
            profile = client.get("/api/v1/student-profiles").json()[0]
            learning_flow = client.post(
                "/api/v1/learning-paths",
                json={
                    "student_profile_id": profile["id"],
                    "course_id": demo["course_id"],
                    "goal": "掌握二叉树遍历并完成前序遍历练习",
                },
            ).json()
            path_item = next(
                item
                for item in learning_flow["learning_path"]["items"]
                if "二叉树遍历" in item["title"]
            )

            response = client.post(
                "/api/v1/resources/generate",
                json={"path_item_id": path_item["id"], "resource_type": "teaching_video"},
            )

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["resource_type"], "teaching_video")
            self.assertIn("动画脚本", body["content"])
            self.assertEqual(body["animation_spec"]["template_id"], "binary_tree_traversal")
            self.assertEqual(body["animation_spec"]["data"]["traversal_type"], "PRE_ORDER")
            self.assertEqual(
                [step["target"] for step in body["animation_spec"]["timeline"]],
                ["A", "B", "D", "E", "C"],
            )

    def test_deleting_user_profile_removes_related_learning_records_and_runs(self) -> None:
        with TestClient(create_app()) as client:
            demo = client.post("/api/v1/demo-data/load").json()["demo_data"]
            profile = client.post(
                "/api/v1/student-profiles/from-dialogue",
                json={"dialogue": "我想用代码练习链表和 BFS，每周 6 小时。"},
            ).json()
            graph = client.get(f"/api/v1/courses/{demo['course_id']}/graph").json()
            learning_flow = client.post(
                "/api/v1/learning-paths",
                json={
                    "student_profile_id": profile["id"],
                    "course_id": demo["course_id"],
                    "goal": "练习链表和 BFS",
                },
            ).json()
            path = learning_flow["learning_path"]
            planner_run_id = learning_flow["agent_run"]["id"]
            path_item = path["items"][0]

            resource = client.post(
                "/api/v1/resources/generate",
                json={"path_item_id": path_item["id"], "resource_type": "coding_case"},
            ).json()
            quiz = client.post(
                "/api/v1/quizzes/generate",
                json={"student_profile_id": profile["id"], "concept_id": graph["concepts"][0]["id"], "difficulty": "basic"},
            ).json()
            attempt = client.post(
                f"/api/v1/quizzes/{quiz['id']}/attempts",
                json={"student_profile_id": profile["id"], "answers": {"answer": quiz["items"][0]["answer"]}},
            ).json()

            delete_response = client.delete(f"/api/v1/student-profiles/{profile['id']}")
            self.assertEqual(delete_response.status_code, 204)
            self.assertEqual(client.get(f"/api/v1/student-profiles/{profile['id']}").status_code, 404)
            self.assertEqual(client.get(f"/api/v1/learning-paths/{path['id']}").status_code, 404)
            for run_id in [planner_run_id, resource["agent_run_id"], quiz["agent_run_id"], attempt["agent_run_id"]]:
                self.assertEqual(client.get(f"/api/v1/agent-runs/{run_id}").status_code, 404)

    def test_loop_endpoints_return_404_for_missing_records(self) -> None:
        with TestClient(create_app()) as client:
            resource = client.post("/api/v1/resources/generate", json={"path_item_id": 999999, "resource_type": "讲义"})
            self.assertEqual(resource.status_code, 404)

            tutor = client.post(
                "/api/v1/tutor/ask",
                json={"student_profile_id": 999999, "course_id": 999999, "question": "x"},
            )
            self.assertEqual(tutor.status_code, 404)

            quiz = client.post(
                "/api/v1/quizzes/generate",
                json={"student_profile_id": 999999, "concept_id": 999999, "difficulty": "basic"},
            )
            self.assertEqual(quiz.status_code, 404)

            attempt = client.post(
                "/api/v1/quizzes/999999/attempts",
                json={"student_profile_id": 999999, "answers": {"answer": "x"}},
            )
            self.assertEqual(attempt.status_code, 404)

            profile_update = client.post("/api/v1/student-profiles/999999/update-from-trace")
            self.assertEqual(profile_update.status_code, 404)
