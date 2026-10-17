import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.db.session import get_engine
from app.main import create_app
from app.services.resource_service import ResourceService
from app.services.task_service import TaskService
from app.services.tutor_service import TutorService


REPO_ROOT = Path(__file__).resolve().parents[1]


class ResourceTutorPostprocessingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "resource-tutor-postprocessing.sqlite3"
        self.database_url = f"sqlite:///{database_path.as_posix()}"
        self.environment = patch.dict(
            os.environ,
            {
                "APP_DATABASE_URL": self.database_url,
                "LLM_PROVIDER": "rule_based",
                "LLM_ENABLE_FOR_RESOURCE": "false",
                "LLM_ENABLE_FOR_TUTOR": "false",
                "LLM_ENABLE_FOR_PROFILE_UPDATER": "false",
            },
        )
        self.environment.start()
        self.client = TestClient(create_app())
        self.client.__enter__()
        self.demo = self.client.post("/api/v1/demo-data/load").json()["demo_data"]
        self.profile = self.client.get("/api/v1/student-profiles").json()[0]
        flow = self.client.post(
            "/api/v1/learning-paths",
            json={
                "student_profile_id": self.profile["id"],
                "course_id": self.demo["course_id"],
                "goal": "系统掌握整门数据结构课程",
            },
        ).json()
        self.path_item_id = flow["learning_path"]["items"][0]["id"]

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        get_engine().dispose()
        get_engine(self.database_url).dispose()
        get_engine.cache_clear()
        self.environment.stop()
        self.temp_dir.cleanup()

    def test_resource_returns_content_before_profile_update_runs(self) -> None:
        with patch(
            "app.services.profile_postprocessing_service.ProfileUpdaterService.update_from_trace",
            side_effect=AssertionError("profile update must not block resource response"),
        ):
            response = ResourceService(database_url=self.database_url).generate_resource(
                self.path_item_id,
                "guided_note",
            )

        self.assertTrue(response.content)
        self.assertEqual(response.postprocessing_status, "pending")
        task = TaskService(database_url=self.database_url).get_task(response.postprocessing_task_id)
        self.assertEqual(task.status, "pending")

    def test_tutor_returns_answer_before_profile_update_runs(self) -> None:
        with patch(
            "app.services.profile_postprocessing_service.ProfileUpdaterService.update_from_trace",
            side_effect=AssertionError("profile update must not block tutor response"),
        ):
            response = TutorService(database_url=self.database_url).ask(
                self.profile["id"],
                self.demo["course_id"],
                "BFS 和 DFS 有什么区别？",
            )

        self.assertTrue(response.answer)
        self.assertEqual(response.postprocessing_status, "pending")
        task = TaskService(database_url=self.database_url).get_task(response.postprocessing_task_id)
        self.assertEqual(task.status, "pending")

    def test_resource_api_exposes_a_completed_profile_update_task(self) -> None:
        response = self.client.post(
            "/api/v1/resources/generate",
            json={"path_item_id": self.path_item_id, "resource_type": "guided_note"},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["content"])
        task = self.client.get(f"/api/v1/tasks/{body['postprocessing_task_id']}")
        self.assertEqual(task.status_code, 200)
        self.assertEqual(task.json()["status"], "completed")

    def test_api_timing_excludes_slow_tutor_profile_postprocessing(self) -> None:
        started = time.perf_counter()
        with patch(
            "app.services.profile_postprocessing_service.ProfileUpdaterService.update_from_trace",
            side_effect=lambda *args, **kwargs: time.sleep(0.5),
        ):
            response = self.client.post(
                "/api/v1/tutor/ask",
                json={
                    "student_profile_id": self.profile["id"],
                    "course_id": self.demo["course_id"],
                    "question": "BFS 和 DFS 有什么区别？",
                },
            )
        wall_duration_ms = round((time.perf_counter() - started) * 1000)

        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(wall_duration_ms, 450)
        self.assertLess(int(response.headers["X-Process-Time-Ms"]), wall_duration_ms - 300)

    def test_frontend_reports_safe_background_progress_without_fake_streaming(self) -> None:
        app_source = (REPO_ROOT / "src/frontend/src/App.tsx").read_text(encoding="utf-8")
        resource_source = (REPO_ROOT / "src/frontend/src/features/resource/ResourceStep.tsx").read_text(encoding="utf-8")
        tutor_source = (REPO_ROOT / "src/frontend/src/features/tutor/TutorStep.tsx").read_text(encoding="utf-8")
        type_source = (REPO_ROOT / "src/frontend/src/api/types.ts").read_text(encoding="utf-8")
        ui_source = app_source + resource_source + tutor_source

        self.assertIn("内容已返回，画像正在后台更新", ui_source)
        self.assertIn("安全校验通过后展示", ui_source)
        self.assertNotIn("回答即将逐字呈现", ui_source)
        self.assertIn("postprocessing_task_id", type_source)


if __name__ == "__main__":
    unittest.main()
