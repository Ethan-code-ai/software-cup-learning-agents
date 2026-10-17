import os
import tempfile
import unittest
from pathlib import Path

from app.db.base import Base
from app.db.session import get_engine, get_session_factory
from app.models import Course, Document, DocumentChunk
from app.schemas import KnowledgeSearchResult
from app.services.citation_service import build_excerpt, source_ref_payload, validate_citations
from app.services.knowledge_base_service import KnowledgeBaseService


class RagCitationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "rag-citations.sqlite3"
        self.database_url = f"sqlite:///{self.database_path.as_posix()}"
        self.previous_database_url = os.environ.get("APP_DATABASE_URL")
        os.environ["APP_DATABASE_URL"] = self.database_url
        Base.metadata.create_all(get_engine(self.database_url))

    def tearDown(self) -> None:
        get_engine().dispose()
        get_engine(self.database_url).dispose()
        get_engine.cache_clear()
        if self.previous_database_url is None:
            os.environ.pop("APP_DATABASE_URL", None)
        else:
            os.environ["APP_DATABASE_URL"] = self.previous_database_url
        self.temp_dir.cleanup()

    def test_build_excerpt_normalizes_and_limits_real_chunk_text(self) -> None:
        content = "BFS uses queue.\n\n" + ("level " * 80)

        excerpt = build_excerpt(content, max_length=80)

        self.assertLessEqual(len(excerpt), 80)
        self.assertTrue(excerpt.startswith("BFS uses queue. level"))
        self.assertNotIn("\n", excerpt)
        self.assertTrue(excerpt.endswith("..."))

    def test_search_result_metadata_contains_source_title_and_excerpt(self) -> None:
        course_id, source_ref = self._seed_document_chunk()

        results = KnowledgeBaseService(database_url=self.database_url).search(course_id, "BFS queue shortest path", top_k=3)

        self.assertTrue(results)
        result = results[0]
        self.assertEqual(result.source_ref, source_ref)
        self.assertEqual(result.metadata["source_ref"], source_ref)
        self.assertEqual(result.metadata["source_title"], "bfs-citation-note.md")
        self.assertIn("BFS uses a queue", result.metadata["excerpt"])
        self.assertLessEqual(len(result.metadata["excerpt"]), 220)

    def test_source_ref_payload_preserves_citation_metadata_for_agents(self) -> None:
        chunk = KnowledgeSearchResult(
            chunk_id=10,
            content="BFS uses a queue.",
            score=0.88,
            source_ref="document:4#chunk:2",
            metadata={
                "source_title": "bfs.md",
                "excerpt": "BFS uses a queue.",
                "retrieval_mode": "hybrid",
                "rerank_score": 0.91,
                "rerank_reasons": ["compare_chunk"],
                "matched_terms": ["bfs"],
                "anchor_matches": ["bfs"],
            },
        )

        payload = source_ref_payload(chunk)

        self.assertEqual(payload["source_ref"], "document:4#chunk:2")
        self.assertEqual(payload["source_title"], "bfs.md")
        self.assertEqual(payload["excerpt"], "BFS uses a queue.")
        self.assertEqual(payload["rerank_score"], 0.91)
        self.assertEqual(payload["rerank_reasons"], ["compare_chunk"])

    def test_validate_citations_detects_fake_and_missing_source_refs(self) -> None:
        source_refs = [{"source_ref": "document:4#chunk:2"}]

        fake = validate_citations("claim [document:999#chunk:1]", source_refs)
        missing = validate_citations("claim without citation", source_refs)
        valid = validate_citations("claim [document:4#chunk:2]", source_refs)

        self.assertEqual(fake["fake_source_refs"], ["document:999#chunk:1"])
        self.assertTrue(missing["missing_citation"])
        self.assertFalse(valid["fake_source_refs"])
        self.assertFalse(valid["missing_citation"])

    def test_validate_citations_resolves_ordinal_and_rejects_fake_non_document_refs(self) -> None:
        source_refs = [
            {"source_ref": "demo.md#linked-list"},
            {"source_ref": "demo://data-structures/graph-search#bfs-dfs"},
        ]

        ordinal = validate_citations("链表由节点组成。[1]", source_refs)
        direct = validate_citations(
            "BFS 按层搜索。[demo://data-structures/graph-search#bfs-dfs]",
            source_refs,
        )
        fake = validate_citations("伪造内容。[demo.md#not-retrieved]", source_refs)
        invalid_ordinal = validate_citations("越界编号。[9]", source_refs)
        code_array = validate_citations(
            "```python\nvalues = [9]\n```\n数组示例来自课程资料。[1]",
            source_refs,
        )

        self.assertEqual(ordinal["cited_source_refs"], ["demo.md#linked-list"])
        self.assertFalse(ordinal["missing_citation"])
        self.assertEqual(direct["cited_source_refs"], ["demo://data-structures/graph-search#bfs-dfs"])
        self.assertEqual(fake["fake_source_refs"], ["demo.md#not-retrieved"])
        self.assertEqual(invalid_ordinal["fake_source_refs"], [])
        self.assertTrue(invalid_ordinal["missing_citation"])
        self.assertEqual(code_array["fake_source_refs"], [])
        self.assertEqual(code_array["cited_source_refs"], ["demo.md#linked-list"])

    def _seed_document_chunk(self) -> tuple[int, str]:
        session = get_session_factory(self.database_url)()
        try:
            course = Course(title="Citation Course", description="citation", is_demo=False)
            session.add(course)
            session.flush()
            document = Document(course_id=course.id, title="bfs-citation-note.md", source_type="markdown", status="ready")
            session.add(document)
            session.flush()
            source_ref = f"document:{document.id}#chunk:0"
            chunk = DocumentChunk(
                document_id=document.id,
                concept_id=None,
                content="BFS uses a queue to expand graph nodes level by level and explain shortest path in unweighted graphs.",
                metadata_json={"chunk_index": 0, "parser": "markdown"},
                source_ref=source_ref,
            )
            session.add(chunk)
            session.commit()
            return course.id, source_ref
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
