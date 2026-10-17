import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.db.session import get_engine, session_scope
from app.main import create_app
from app.models import Attempt
from app.services.assessment_service import AssessmentService
from app.services.task_service import TaskService


class QuizPostprocessingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "quiz-postprocessing.sqlite3"
        self.database_url = f"sqlite:///{database_path.as_posix()}"
        self.environment = patch.dict(
            os.environ,
            {
                "APP_DATABASE_URL": self.database_url,
                "LLM_PROVIDER": "rule_based",
                "LLM_ENABLE_FOR_EVALUATOR": "false",
                "LLM_ENABLE_FOR_PROFILE_UPDATER": "false",
                "LLM_ENABLE_FOR_PLANNER": "false",
                "LLM_ENABLE_FOR_QUIZ": "false",
            },
        )
        self.environment.start()
        self.client = TestClient(create_app())
        self.client.__enter__()
        demo = self.client.post("/api/v1/demo-data/load").json()["demo_data"]
        self.profile = self.client.get("/api/v1/student-profiles").json()[0]
        self.flow = self.client.post(
            "/api/v1/learning-paths",
            json={
                "student_profile_id": self.profile["id"],
                "course_id": demo["course_id"],
                "goal": "系统掌握整门数据结构课程",
            },
        ).json()
        concept_id = self.flow["learning_path"]["items"][0]["concept_id"]
        self.quiz = self.client.post(
            "/api/v1/quizzes/generate",
            json={
                "student_profile_id": self.profile["id"],
                "concept_id": concept_id,
                "difficulty": "basic",
            },
        ).json()

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        get_engine().dispose()
        get_engine(self.database_url).dispose()
        get_engine.cache_clear()
        self.environment.stop()
        self.temp_dir.cleanup()

    def test_submit_persists_score_without_running_slow_postprocessing(self) -> None:
        with (
            patch(
                "app.services.assessment_service.ProfileUpdaterService.update_from_trace",
                side_effect=AssertionError("profile update must not run in submit_attempt"),
            ),
            patch(
                "app.services.assessment_service.LearningPathService.refresh_active_paths",
                side_effect=AssertionError("planner must not run in submit_attempt"),
            ),
        ):
            result = AssessmentService(database_url=self.database_url).submit_attempt(
                self.quiz["id"],
                self.profile["id"],
                {"answer": self.quiz["items"][0]["answer"]},
                learning_path_id=self.flow["learning_path"]["id"],
            )

        self.assertEqual(result.score, 1.0)
        self.assertEqual(result.postprocessing_status, "pending")
        self.assertIsNotNone(result.postprocessing_task_id)
        task = TaskService(database_url=self.database_url).get_task(result.postprocessing_task_id)
        self.assertEqual(task.status, "pending")

    def test_background_processing_refreshes_only_the_selected_path(self) -> None:
        result = AssessmentService(database_url=self.database_url).submit_attempt(
            self.quiz["id"],
            self.profile["id"],
            {"answer": self.quiz["items"][0]["answer"]},
            learning_path_id=self.flow["learning_path"]["id"],
        )

        with (
            patch(
                "app.services.assessment_service.ProfileUpdaterService.update_from_trace"
            ) as update_profile,
            patch(
                "app.services.assessment_service.LearningPathService.refresh_active_paths",
                return_value=[],
            ) as refresh_path,
        ):
            AssessmentService(database_url=self.database_url).process_attempt_postprocessing(
                result.postprocessing_task_id
            )

        update_profile.assert_called_once()
        refresh_path.assert_called_once_with(
            self.profile["id"],
            self.flow["learning_path"]["course_id"],
            trigger=f"quiz:{result.attempt_id}",
            path_id=self.flow["learning_path"]["id"],
        )
        task = TaskService(database_url=self.database_url).get_task(result.postprocessing_task_id)
        self.assertEqual(task.status, "completed")

    def test_background_failure_keeps_attempt_and_exposes_failed_task(self) -> None:
        result = AssessmentService(database_url=self.database_url).submit_attempt(
            self.quiz["id"],
            self.profile["id"],
            {"answer": self.quiz["items"][0]["answer"]},
            learning_path_id=self.flow["learning_path"]["id"],
        )

        with patch(
            "app.services.assessment_service.ProfileUpdaterService.update_from_trace",
            side_effect=TimeoutError("remote profile update timed out"),
        ):
            AssessmentService(database_url=self.database_url).process_attempt_postprocessing(
                result.postprocessing_task_id
            )

        task = TaskService(database_url=self.database_url).get_task(result.postprocessing_task_id)
        self.assertEqual(task.status, "failed")
        self.assertIn("TimeoutError", task.error)
        with session_scope(self.database_url) as session:
            attempt = session.get(Attempt, result.attempt_id)
            self.assertIsNotNone(attempt)
            self.assertEqual(attempt.score, 1.0)

    def test_background_failure_redacts_environment_secrets(self) -> None:
        result = AssessmentService(database_url=self.database_url).submit_attempt(
            self.quiz["id"],
            self.profile["id"],
            {"answer": self.quiz["items"][0]["answer"]},
            learning_path_id=self.flow["learning_path"]["id"],
        )
        secret = "perf-test-secret-123456"

        with (
            patch.dict(os.environ, {"LLM_API_KEY": secret}),
            patch(
                "app.services.assessment_service.ProfileUpdaterService.update_from_trace",
                side_effect=RuntimeError(f"provider rejected api_key={secret}"),
            ),
        ):
            AssessmentService(database_url=self.database_url).process_attempt_postprocessing(
                result.postprocessing_task_id
            )

        task = TaskService(database_url=self.database_url).get_task(result.postprocessing_task_id)
        self.assertEqual(task.status, "failed")
        self.assertNotIn(secret, task.error)
        self.assertIn("[REDACTED]", task.error)

    def test_attempt_api_returns_queryable_postprocessing_task(self) -> None:
        response = self.client.post(
            f"/api/v1/quizzes/{self.quiz['id']}/attempts",
            json={
                "student_profile_id": self.profile["id"],
                "answers": {"answer": self.quiz["items"][0]["answer"]},
                "learning_path_id": self.flow["learning_path"]["id"],
            },
        )

        self.assertEqual(response.status_code, 200)
        evaluation = response.json()
        self.assertIsNotNone(evaluation["postprocessing_task_id"])
        task_response = self.client.get(f"/api/v1/tasks/{evaluation['postprocessing_task_id']}")
        self.assertEqual(task_response.status_code, 200)
        self.assertEqual(task_response.json()["status"], "completed")

    def test_postprocessing_can_be_disabled_without_affecting_score(self) -> None:
        response = self.client.post(
            f"/api/v1/quizzes/{self.quiz['id']}/attempts",
            json={
                "student_profile_id": self.profile["id"],
                "answers": {"answer": self.quiz["items"][0]["answer"]},
                "run_postprocessing": False,
            },
        )

        self.assertEqual(response.status_code, 200)
        evaluation = response.json()
        self.assertEqual(evaluation["score"], 1.0)
        self.assertIsNone(evaluation["postprocessing_task_id"])
        self.assertEqual(evaluation["postprocessing_status"], "not_requested")


if __name__ == "__main__":
    unittest.main()
