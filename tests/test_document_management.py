import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.db.base import Base
from app.db.session import get_engine, get_session_factory
from app.main import create_app
from app.models import Course


class DocumentManagementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "document-management.sqlite3"
        self.database_url = f"sqlite:///{self.database_path.as_posix()}"
        self.previous_database_url = os.environ.get("APP_DATABASE_URL")
        self.previous_embedding_enabled = os.environ.get("RAG_EMBEDDING_ENABLED")
        os.environ["APP_DATABASE_URL"] = self.database_url
        os.environ["RAG_EMBEDDING_ENABLED"] = "false"
        Base.metadata.create_all(get_engine(self.database_url))
        self.course_id = self._seed_course()

    def tearDown(self) -> None:
        get_engine().dispose()
        get_engine(self.database_url).dispose()
        get_engine.cache_clear()
        if self.previous_database_url is None:
            os.environ.pop("APP_DATABASE_URL", None)
        else:
            os.environ["APP_DATABASE_URL"] = self.previous_database_url
        if self.previous_embedding_enabled is None:
            os.environ.pop("RAG_EMBEDDING_ENABLED", None)
        else:
            os.environ["RAG_EMBEDDING_ENABLED"] = self.previous_embedding_enabled
        self.temp_dir.cleanup()

    def test_document_list_detail_and_delete_exclude_chunks_from_search(self) -> None:
        with TestClient(create_app()) as client:
            document = self._ingest_document(client)
            document_id = document["id"]
            source_ref = f"document:{document_id}#chunk:0"

            listing = client.get(f"/api/v1/courses/{self.course_id}/documents")
            self.assertEqual(listing.status_code, 200)
            documents = listing.json()
            self.assertEqual(documents[0]["id"], document_id)
            self.assertEqual(documents[0]["chunk_count"], 1)
            self.assertEqual(documents[0]["status"], "completed")

            detail = client.get(f"/api/v1/documents/{document_id}")
            self.assertEqual(detail.status_code, 200)
            self.assertEqual(detail.json()["title"], "deletable-bfs.md")

            search_before = client.post(
                "/api/v1/knowledge/search",
                json={"course_id": self.course_id, "query": "BFS queue shortest path", "top_k": 3},
            )
            self.assertEqual(search_before.status_code, 200)
            self.assertIn(source_ref, {result["source_ref"] for result in search_before.json()["results"]})

            delete = client.delete(f"/api/v1/documents/{document_id}")
            self.assertEqual(delete.status_code, 204)

            listing_after = client.get(f"/api/v1/courses/{self.course_id}/documents")
            self.assertEqual(listing_after.status_code, 200)
            self.assertNotIn(document_id, {item["id"] for item in listing_after.json()})

            chunks_after = client.get(f"/api/v1/documents/{document_id}/chunks")
            self.assertEqual(chunks_after.status_code, 404)

            search_after = client.post(
                "/api/v1/knowledge/search",
                json={"course_id": self.course_id, "query": "BFS queue shortest path", "top_k": 3},
            )
            self.assertEqual(search_after.status_code, 200)
            self.assertNotIn(source_ref, {result["source_ref"] for result in search_after.json()["results"]})

    def test_demo_seed_document_delete_is_protected(self) -> None:
        with TestClient(create_app()) as client:
            demo = client.post("/api/v1/demo-data/load").json()["demo_data"]
            listing = client.get(f"/api/v1/courses/{demo['course_id']}/documents")
            self.assertEqual(listing.status_code, 200)
            demo_document = next(item for item in listing.json() if item["source_type"] == "seed")

            response = client.delete(f"/api/v1/documents/{demo_document['id']}")

            self.assertEqual(response.status_code, 409)

    def test_reindex_document_returns_disabled_result_when_embedding_is_off(self) -> None:
        with TestClient(create_app()) as client:
            document = self._ingest_document(client)

            response = client.post(f"/api/v1/documents/{document['id']}/reindex")

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["document_id"], document["id"])
            self.assertFalse(payload["enabled"])
            self.assertEqual(payload["indexed"], 0)
            self.assertEqual(payload["skipped"], 0)
            self.assertEqual(payload["failed"], 0)

    def _ingest_document(self, client: TestClient) -> dict:
        response = client.post(
            f"/api/v1/courses/{self.course_id}/documents",
            json={
                "title": "deletable-bfs.md",
                "source_type": "markdown",
                "content": "# BFS\nBFS uses queue for shortest path in unweighted graph.",
            },
        )
        self.assertEqual(response.status_code, 200)
        return response.json()["document"]

    def _seed_course(self) -> int:
        session = get_session_factory(self.database_url)()
        try:
            course = Course(title="Document Management Course", description="docs", is_demo=False)
            session.add(course)
            session.commit()
            return course.id
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
