import os
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import select

from app.adapters.protocols import EmbeddingResult
from app.db.base import Base
from app.db.session import get_engine, get_session_factory
from app.models import ChunkEmbedding, Course, Document, DocumentChunk
from app.services.embedding_index_service import EmbeddingIndexService
from app.services.knowledge_base_service import KnowledgeBaseService
from app.services.vector_search_service import SQLiteVectorSearchService, cosine_similarity


class FakeEmbeddingProvider:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[str] = []

    def embed(self, text: str) -> EmbeddingResult:
        self.calls.append(text)
        if self.fail:
            raise RuntimeError("fake embedding failure")
        normalized = text.lower()
        if "queue" in normalized or "breadth" in normalized or "bfs" in normalized:
            vector = [1.0, 0.0, 0.0]
        elif "stack" in normalized or "recursion" in normalized or "dfs" in normalized:
            vector = [0.0, 1.0, 0.0]
        else:
            vector = [0.2, 0.2, 0.0]
        return EmbeddingResult(vector=vector, metadata={"provider": "fake", "model": "fake-v1"})


class VectorRetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "vector.sqlite3"
        self.database_url = f"sqlite:///{self.database_path.as_posix()}"
        os.environ["APP_DATABASE_URL"] = self.database_url
        Base.metadata.create_all(get_engine(self.database_url))
        self.course_id, self.other_course_id = self._seed_documents()

    def tearDown(self) -> None:
        get_engine().dispose()
        get_engine(self.database_url).dispose()
        get_engine.cache_clear()
        os.environ.pop("APP_DATABASE_URL", None)
        os.environ.pop("RAG_EMBEDDING_ENABLED", None)
        os.environ.pop("RAG_RETRIEVAL_MODE", None)
        self.temp_dir.cleanup()

    def test_cosine_similarity_orders_related_vectors(self) -> None:
        self.assertAlmostEqual(cosine_similarity([1, 0], [1, 0]), 1.0)
        self.assertAlmostEqual(cosine_similarity([1, 0], [0, 1]), 0.0)
        self.assertEqual(cosine_similarity([0, 0], [1, 0]), 0.0)

    def test_indexing_writes_embeddings_and_skips_duplicates(self) -> None:
        provider = FakeEmbeddingProvider()
        first = EmbeddingIndexService(
            database_url=self.database_url,
            provider=provider,
            provider_name="fake",
            model="fake-v1",
        ).index_course(self.course_id)
        second = EmbeddingIndexService(
            database_url=self.database_url,
            provider=provider,
            provider_name="fake",
            model="fake-v1",
        ).index_course(self.course_id)

        self.assertEqual(first.indexed, 2)
        self.assertEqual(first.skipped, 0)
        self.assertEqual(second.indexed, 0)
        self.assertEqual(second.skipped, 2)

        session = get_session_factory(self.database_url)()
        try:
            embeddings = session.scalars(select(ChunkEmbedding)).all()
            self.assertEqual(len(embeddings), 2)
            self.assertEqual({embedding.provider for embedding in embeddings}, {"fake"})
        finally:
            session.close()

    def test_changed_chunk_content_gets_new_content_hash(self) -> None:
        provider = FakeEmbeddingProvider()
        indexer = EmbeddingIndexService(
            database_url=self.database_url,
            provider=provider,
            provider_name="fake",
            model="fake-v1",
        )
        indexer.index_course(self.course_id)

        session = get_session_factory(self.database_url)()
        try:
            chunk = session.scalars(select(DocumentChunk).where(DocumentChunk.content.contains("BFS"))).first()
            self.assertIsNotNone(chunk)
            chunk.content = "BFS queue level order changed content."
            session.commit()
        finally:
            session.close()

        result = indexer.index_course(self.course_id)
        self.assertEqual(result.indexed, 1)

        session = get_session_factory(self.database_url)()
        try:
            embeddings = session.scalars(select(ChunkEmbedding)).all()
            self.assertEqual(len(embeddings), 3)
        finally:
            session.close()

    def test_vector_search_is_scoped_to_current_course(self) -> None:
        provider = FakeEmbeddingProvider()
        EmbeddingIndexService(self.database_url, provider, "fake", "fake-v1").index_course(self.course_id)
        EmbeddingIndexService(self.database_url, provider, "fake", "fake-v1").index_course(self.other_course_id)

        results = SQLiteVectorSearchService(database_url=self.database_url, provider=provider).search(
            self.course_id,
            "breadth queue search",
            top_k=5,
        )

        self.assertTrue(results)
        self.assertTrue(all(result.metadata["document_id"] in {1} for result in results))
        self.assertEqual(results[0].metadata["retrieval_mode"], "vector")
        self.assertGreater(results[0].metadata["vector_score"], 0)

    def test_hybrid_search_adds_vector_score_without_changing_api_shape(self) -> None:
        os.environ["RAG_EMBEDDING_ENABLED"] = "true"
        os.environ["RAG_RETRIEVAL_MODE"] = "hybrid"
        provider = FakeEmbeddingProvider()
        EmbeddingIndexService(self.database_url, provider, "fake", "fake-v1").index_course(self.course_id)

        results = KnowledgeBaseService(database_url=self.database_url, embedding_provider=provider).search(
            self.course_id,
            "breadth-first exploration",
            top_k=2,
        )

        self.assertTrue(results)
        self.assertEqual(results[0].metadata["retrieval_mode"], "hybrid")
        self.assertIn("keyword_score", results[0].metadata)
        self.assertIn("vector_score", results[0].metadata)
        self.assertEqual(results[0].source_ref, "document:1#chunk:0")

    def test_vector_failure_falls_back_to_keyword_results(self) -> None:
        os.environ["RAG_EMBEDDING_ENABLED"] = "true"
        os.environ["RAG_RETRIEVAL_MODE"] = "hybrid"
        results = KnowledgeBaseService(database_url=self.database_url, embedding_provider=FakeEmbeddingProvider(fail=True)).search(
            self.course_id,
            "BFS queue",
            top_k=2,
        )

        self.assertTrue(results)
        self.assertEqual(results[0].metadata["retrieval_mode"], "keyword")
        self.assertEqual(results[0].source_ref, "document:1#chunk:0")

    def _seed_documents(self) -> tuple[int, int]:
        session = get_session_factory(self.database_url)()
        try:
            course = Course(title="Vector Course", description="test", is_demo=False)
            other_course = Course(title="Other Course", description="test", is_demo=False)
            session.add_all([course, other_course])
            session.flush()

            document = Document(course_id=course.id, title="graph.md", source_type="markdown", status="completed")
            other_document = Document(course_id=other_course.id, title="other.md", source_type="markdown", status="completed")
            session.add_all([document, other_document])
            session.flush()

            session.add_all(
                [
                    DocumentChunk(
                        document_id=document.id,
                        concept_id=None,
                        content="BFS uses a queue and breadth-first level exploration.",
                        vector_ref=None,
                        metadata_json={"document_id": document.id},
                        source_ref="document:1#chunk:0",
                    ),
                    DocumentChunk(
                        document_id=document.id,
                        concept_id=None,
                        content="DFS uses a stack or recursion for depth-first traversal.",
                        vector_ref=None,
                        metadata_json={"document_id": document.id},
                        source_ref="document:1#chunk:1",
                    ),
                    DocumentChunk(
                        document_id=other_document.id,
                        concept_id=None,
                        content="BFS queue content from another course must not be searched.",
                        vector_ref=None,
                        metadata_json={"document_id": other_document.id},
                        source_ref="document:2#chunk:0",
                    ),
                ]
            )
            session.commit()
            return course.id, other_course.id
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
