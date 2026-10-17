import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.session import get_engine, get_session_factory
from app.main import create_app
from app.models import Course, Document, DocumentChunk


class RagIngestionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "rag-ingestion.sqlite3"
        self.database_url = f"sqlite:///{self.database_path.as_posix()}"
        os.environ["APP_DATABASE_URL"] = self.database_url

    def tearDown(self) -> None:
        get_engine().dispose()
        get_engine(self.database_url).dispose()
        get_engine.cache_clear()
        os.environ.pop("APP_DATABASE_URL", None)
        self.temp_dir.cleanup()

    def test_text_document_ingestion_creates_document_chunks_and_stable_source_refs(self) -> None:
        with TestClient(create_app()) as client:
            client.post("/api/v1/demo-data/load")
            course_id = client.get("/api/v1/demo-data/status").json()["course_id"]

            response = client.post(
                f"/api/v1/courses/{course_id}/documents",
                json={
                    "title": "bfs-note.md",
                    "source_type": "markdown",
                    "content": "# BFS\nBFS 按层扩展，适合无权图最短路径。\n\n## Queue\nBFS 使用 queue 保存待访问节点。",
                },
            )

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["document"]["title"], "bfs-note.md")
            self.assertEqual(body["document"]["status"], "completed")
            self.assertGreaterEqual(body["chunk_count"], 1)
            first_chunk = body["chunks"][0]
            self.assertEqual(first_chunk["source_ref"], f"document:{body['document']['id']}#chunk:0")
            self.assertEqual(first_chunk["metadata"]["chunk_index"], 0)
            self.assertIn("char_start", first_chunk["metadata"])
            self.assertIn("char_end", first_chunk["metadata"])

            chunks_response = client.get(f"/api/v1/documents/{body['document']['id']}/chunks")
            self.assertEqual(chunks_response.status_code, 200)
            self.assertEqual(chunks_response.json()[0]["source_ref"], first_chunk["source_ref"])

            session = get_session_factory(self.database_url)()
            try:
                document = session.get(Document, body["document"]["id"])
                chunks = session.scalars(
                    select(DocumentChunk).where(DocumentChunk.document_id == body["document"]["id"])
                ).all()
                self.assertIsNotNone(document)
                self.assertEqual(len(chunks), body["chunk_count"])
            finally:
                session.close()

    def test_document_ingestion_returns_errors_without_partial_document(self) -> None:
        with TestClient(create_app()) as client:
            client.post("/api/v1/demo-data/load")
            course_id = client.get("/api/v1/demo-data/status").json()["course_id"]

            response = client.post(
                f"/api/v1/courses/{course_id}/documents",
                json={"title": "bad.pdf", "source_type": "pdf", "content": "not supported"},
            )
            self.assertEqual(response.status_code, 400)

            missing_course = client.post(
                "/api/v1/courses/999999/documents",
                json={"title": "note.txt", "source_type": "text", "content": "hello"},
            )
            self.assertEqual(missing_course.status_code, 404)

            session = get_session_factory(self.database_url)()
            try:
                self.assertIsNone(session.scalar(select(Document).where(Document.title == "bad.pdf")))
            finally:
                session.close()

    def test_duplicate_document_ingestion_reuses_existing_active_document(self) -> None:
        with TestClient(create_app()) as client:
            client.post("/api/v1/demo-data/load")
            course_id = client.get("/api/v1/demo-data/status").json()["course_id"]
            payload = {
                "title": "bfs-duplicate.md",
                "source_type": "markdown",
                "content": "# BFS\nBFS uses a queue for shortest path.",
            }

            first = client.post(f"/api/v1/courses/{course_id}/documents", json=payload)
            second = client.post(f"/api/v1/courses/{course_id}/documents", json=payload)

            self.assertEqual(first.status_code, 200)
            self.assertEqual(second.status_code, 200)
            self.assertEqual(first.json()["document"]["id"], second.json()["document"]["id"])

            listing = client.get(f"/api/v1/courses/{course_id}/documents")
            matching = [document for document in listing.json() if document["title"] == "bfs-duplicate.md"]
            self.assertEqual(len(matching), 1)

    def test_reimport_deleted_duplicate_restores_existing_document_id(self) -> None:
        with TestClient(create_app()) as client:
            client.post("/api/v1/demo-data/load")
            course_id = client.get("/api/v1/demo-data/status").json()["course_id"]
            payload = {
                "title": "bfs-restore.md",
                "source_type": "markdown",
                "content": "# BFS\nBFS uses a queue for shortest path.",
            }

            first = client.post(f"/api/v1/courses/{course_id}/documents", json=payload)
            document_id = first.json()["document"]["id"]
            delete = client.delete(f"/api/v1/documents/{document_id}")
            second = client.post(f"/api/v1/courses/{course_id}/documents", json=payload)

            self.assertEqual(delete.status_code, 204)
            self.assertEqual(second.status_code, 200)
            self.assertEqual(second.json()["document"]["id"], document_id)
            self.assertEqual(second.json()["document"]["status"], "completed")

            listing = client.get(f"/api/v1/courses/{course_id}/documents")
            matching = [document for document in listing.json() if document["title"] == "bfs-restore.md"]
            self.assertEqual(len(matching), 1)
            self.assertEqual(matching[0]["id"], document_id)

    def test_document_chunks_endpoint_returns_404_for_missing_document(self) -> None:
        with TestClient(create_app()) as client:
            response = client.get("/api/v1/documents/999999/chunks")
            self.assertEqual(response.status_code, 404)


class RagIngestionWithoutDemoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "rag-ingestion-no-demo.sqlite3"
        self.database_url = f"sqlite:///{self.database_path.as_posix()}"
        os.environ["APP_DATABASE_URL"] = self.database_url

    def tearDown(self) -> None:
        get_engine().dispose()
        get_engine(self.database_url).dispose()
        get_engine.cache_clear()
        os.environ.pop("APP_DATABASE_URL", None)
        self.temp_dir.cleanup()

    def test_ingestion_works_with_real_course_without_demo_seed(self) -> None:
        from app.db.base import Base

        Base.metadata.create_all(get_engine(self.database_url))
        session = get_session_factory(self.database_url)()
        try:
            course = Course(title="Real RAG Course", description="test", is_demo=False)
            session.add(course)
            session.commit()
            course_id = course.id
        finally:
            session.close()

        with TestClient(create_app()) as client:
            response = client.post(
                f"/api/v1/courses/{course_id}/documents",
                json={
                    "title": "real-note.txt",
                    "source_type": "text",
                    "content": "真实资料：BFS 使用队列按层遍历。",
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["chunk_count"], 1)
