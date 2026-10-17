import os
import unittest

from app.schemas import KnowledgeSearchResult
from app.services.knowledge_base_service import KnowledgeBaseService
from app.services.reranking_service import RuleBasedReranker, rerank_enabled


class RagRerankingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_rerank_enabled = os.environ.get("RAG_RERANK_ENABLED")

    def tearDown(self) -> None:
        if self.previous_rerank_enabled is None:
            os.environ.pop("RAG_RERANK_ENABLED", None)
        else:
            os.environ["RAG_RERANK_ENABLED"] = self.previous_rerank_enabled

    def test_rerank_is_disabled_by_default_and_service_keeps_order(self) -> None:
        os.environ.pop("RAG_RERANK_ENABLED", None)
        results = [_result("document:1#chunk:0", "plain BFS", 0.2), _result("document:1#chunk:1", "BFS DFS compare", 1.0)]

        self.assertFalse(rerank_enabled())
        reranked = KnowledgeBaseService()._maybe_rerank(results, top_k=2)

        self.assertEqual(reranked, results)
        self.assertNotIn("rerank_score", reranked[0].metadata)

    def test_rule_based_reranker_prioritizes_bfs_dfs_compare_chunk(self) -> None:
        results = [
            _result("document:1#chunk:0", "BFS uses queue.", 1.0, ["bfs"], ["bfs", "dfs"], "bfs"),
            _result(
                "document:1#chunk:1",
                "BFS uses queue while DFS uses stack and recursion. Compare shortest path and backtracking.",
                0.9,
                ["bfs", "dfs"],
                ["bfs", "dfs"],
                "bfs_dfs_compare",
            ),
            _result("document:1#chunk:2", "DFS uses stack.", 1.0, ["dfs"], ["bfs", "dfs"], "dfs"),
        ]

        reranked = RuleBasedReranker().rerank(results, top_k=3)

        self.assertEqual(reranked[0].source_ref, "document:1#chunk:1")
        self.assertIn("rerank_score", reranked[0].metadata)
        self.assertIn("compare_chunk", reranked[0].metadata["rerank_reasons"])
        self.assertIn("covers_required_anchor:bfs", reranked[0].metadata["rerank_reasons"])
        self.assertIn("covers_required_anchor:dfs", reranked[0].metadata["rerank_reasons"])

    def test_context_budget_limits_selected_chunks_without_fake_sources(self) -> None:
        results = [
            _result("document:1#chunk:0", "A" * 50, 1.0),
            _result("document:1#chunk:1", "B" * 80, 0.9),
            _result("document:1#chunk:2", "C" * 30, 0.8),
        ]

        reranked = RuleBasedReranker(top_context=5, char_limit=100).rerank(results, top_k=5)

        self.assertEqual([item.source_ref for item in reranked], ["document:1#chunk:0", "document:1#chunk:2"])
        self.assertTrue(all(item.source_ref and item.source_ref.startswith("document:") for item in reranked))


def _result(
    source_ref: str,
    content: str,
    score: float,
    anchor_matches: list[str] | None = None,
    required_anchors: list[str] | None = None,
    coverage_bucket: str = "general",
) -> KnowledgeSearchResult:
    return KnowledgeSearchResult(
        chunk_id=int(source_ref.rsplit(":", 1)[-1]),
        content=content,
        score=score,
        source_ref=source_ref,
        metadata={
            "source_ref": source_ref,
            "document_id": source_ref.split("#", 1)[0].replace("document:", ""),
            "anchor_matches": anchor_matches or [],
            "required_anchors": required_anchors or [],
            "coverage_bucket": coverage_bucket,
        },
    )


if __name__ == "__main__":
    unittest.main()
