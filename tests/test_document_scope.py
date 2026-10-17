import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.db.base import Base
from app.db.session import get_engine, get_session_factory
from app.main import create_app
from app.models import Course


class DocumentScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "document-scope.sqlite3"
        self.database_url = f"sqlite:///{self.database_path.as_posix()}"
        self.previous_database_url = os.environ.get("APP_DATABASE_URL")
        os.environ["APP_DATABASE_URL"] = self.database_url
        Base.metadata.create_all(get_engine(self.database_url))
        self.course_id = self._seed_course("Scope Course A")
        self.other_course_id = self._seed_course("Scope Course B")

    def tearDown(self) -> None:
        get_engine().dispose()
        get_engine(self.database_url).dispose()
        get_engine.cache_clear()
        if self.previous_database_url is None:
            os.environ.pop("APP_DATABASE_URL", None)
        else:
            os.environ["APP_DATABASE_URL"] = self.previous_database_url
        self.temp_dir.cleanup()

    def test_private_document_only_visible_to_owner_user(self) -> None:
        with TestClient(create_app()) as client:
            private_document = client.post(
                f"/api/v1/courses/{self.course_id}/documents",
                json={
                    "title": "private-bfs.md",
                    "source_type": "markdown",
                    "visibility": "private",
                    "owner_user_id": 7,
                    "content": "# Private BFS\nprivate-bfs-token queue shortest path.",
                },
            )
            self.assertEqual(private_document.status_code, 200, private_document.text)
            private_source = private_document.json()["chunks"][0]["source_ref"]

            no_owner = client.post(
                "/api/v1/knowledge/search",
                json={"course_id": self.course_id, "query": "private-bfs-token", "top_k": 5},
            )
            self.assertEqual(no_owner.status_code, 200)
            self.assertNotIn(private_source, {item["source_ref"] for item in no_owner.json()["results"]})

            wrong_owner = client.post(
                "/api/v1/knowledge/search",
                json={"course_id": self.course_id, "query": "private-bfs-token", "top_k": 5, "owner_user_id": 8},
            )
            self.assertEqual(wrong_owner.status_code, 200)
            self.assertNotIn(private_source, {item["source_ref"] for item in wrong_owner.json()["results"]})

            owner = client.post(
                "/api/v1/knowledge/search",
                json={"course_id": self.course_id, "query": "private-bfs-token", "top_k": 5, "owner_user_id": 7},
            )
            self.assertEqual(owner.status_code, 200)
            self.assertIn(private_source, {item["source_ref"] for item in owner.json()["results"]})

    def test_course_documents_do_not_cross_course_boundary(self) -> None:
        with TestClient(create_app()) as client:
            document = client.post(
                f"/api/v1/courses/{self.course_id}/documents",
                json={
                    "title": "course-a.md",
                    "source_type": "markdown",
                    "content": "# Course A\ncourse-a-only-token BFS queue.",
                },
            )
            self.assertEqual(document.status_code, 200, document.text)
            source_ref = document.json()["chunks"][0]["source_ref"]

            same_course = client.post(
                "/api/v1/knowledge/search",
                json={"course_id": self.course_id, "query": "course-a-only-token", "top_k": 5},
            )
            self.assertIn(source_ref, {item["source_ref"] for item in same_course.json()["results"]})

            other_course = client.post(
                "/api/v1/knowledge/search",
                json={"course_id": self.other_course_id, "query": "course-a-only-token", "top_k": 5},
            )
            self.assertEqual(other_course.status_code, 200)
            self.assertNotIn(source_ref, {item["source_ref"] for item in other_course.json()["results"]})

    def _seed_course(self, title: str) -> int:
        session = get_session_factory(self.database_url)()
        try:
            course = Course(title=title, description="docs", is_demo=False)
            session.add(course)
            session.commit()
            return course.id
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
