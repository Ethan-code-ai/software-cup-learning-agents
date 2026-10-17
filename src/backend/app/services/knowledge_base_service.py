import os
import re

from app.adapters.embedding_provider import EmbeddingSettings, build_embedding_provider
from sqlalchemy import or_, select

from app.db.schema_compat import ensure_document_columns
from app.db.session import session_scope
from app.models import Document, DocumentChunk
from app.schemas import KnowledgeSearchResult
from app.services.citation_service import build_source_metadata
from app.services.reranking_service import RuleBasedReranker, rerank_enabled
from app.services.vector_search_service import SQLiteVectorSearchService


ANCHOR_TERMS = {
    "bfs": ["bfs", "breadth first", "breadth-first", "queue", "level", "\u5e7f\u5ea6\u4f18\u5148", "\u961f\u5217"],
    "dfs": ["dfs", "depth first", "depth-first", "stack", "recursion", "recursive", "backtracking", "\u6df1\u5ea6\u4f18\u5148", "\u6808", "\u9012\u5f52"],
}


QUERY_EXPANSIONS = [
    (["\u65e0\u6743\u56fe"], ["unweighted", "unweighted graph"]),
    (["\u6700\u77ed\u8def\u5f84", "\u6700\u5c11\u8fb9\u6570", "\u6700\u5c11\u8fb9"], ["shortest path", "fewest edges", "edge count"]),
    (["\u7b2c\u4e00\u6b21\u5230\u8fbe", "\u9996\u6b21\u5230\u8fbe"], ["first time", "reaches", "reached"]),
    (["\u961f\u5217"], ["queue", "fifo", "enqueue", "dequeue"]),
    (["\u6808"], ["stack", "lifo"]),
    (["\u6309\u5c42", "\u5c42\u6b21"], ["level", "level by level"]),
    (["\u5bf9\u6bd4", "\u6bd4\u8f83"], ["compare", "comparison", "versus"]),
]

ANCHOR_EXPANSIONS = {
    "bfs": ["bfs", "queue", "level", "shortest path", "unweighted graph", "fewest edges"],
    "dfs": ["dfs", "stack", "recursion", "backtracking"],
}


class KnowledgeBaseService:
    def __init__(self, database_url: str | None = None, embedding_provider=None) -> None:
        self.database_url = database_url
        self.embedding_provider = embedding_provider

    def search(
        self,
        course_id: int,
        query: str,
        top_k: int,
        owner_user_id: int | None = None,
    ) -> list[KnowledgeSearchResult]:
        if top_k <= 0:
            return []
        mode = _retrieval_mode()
        keyword_results = self._keyword_search(course_id, query, top_k, owner_user_id)
        if mode == "keyword":
            return self._maybe_rerank(keyword_results, top_k)

        vector_results = self._vector_search(course_id, query, top_k, owner_user_id)
        if mode == "vector":
            return self._maybe_rerank(vector_results or keyword_results, top_k)
        if not vector_results:
            return self._maybe_rerank(keyword_results, top_k)
        return self._maybe_rerank(self._hybrid_rank(keyword_results, vector_results, top_k), top_k)

    def _keyword_search(
        self,
        course_id: int,
        query: str,
        top_k: int,
        owner_user_id: int | None = None,
    ) -> list[KnowledgeSearchResult]:
        query_terms = self._query_terms(query)
        if not query_terms:
            return []
        required_anchors = self._anchor_matches(query.lower())
        ensure_document_columns(self.database_url)
        with session_scope(self.database_url) as session:
            statement = (
                select(DocumentChunk, Document)
                .join(Document, Document.id == DocumentChunk.document_id)
                .where(Document.course_id == course_id)
                .where(Document.status != "deleted")
                .order_by(DocumentChunk.id)
            )
            if owner_user_id is None:
                statement = statement.where(Document.visibility.in_(["course", "demo"]))
            else:
                statement = statement.where(
                    or_(Document.visibility.in_(["course", "demo"]), Document.owner_user_id == owner_user_id)
                )
            rows = session.execute(statement).all()
            ranked: list[KnowledgeSearchResult] = []
            for chunk, document in rows:
                haystack = f"{chunk.content} {chunk.source_ref or ''} {chunk.metadata_json}".lower()
                content_text = chunk.content.lower()
                matched_terms = self._matched_terms(haystack, query_terms)
                anchor_matches = self._anchor_matches(content_text)
                score = self._score_from_matches(matched_terms, query_terms, haystack, anchor_matches, required_anchors)
                if score <= 0:
                    continue
                content_fingerprint = self._content_fingerprint(chunk.content)
                metadata = build_source_metadata(
                    content=chunk.content,
                    document_title=document.title,
                    metadata={
                        **(chunk.metadata_json if isinstance(chunk.metadata_json, dict) else {}),
                        "document_id": chunk.document_id,
                        "chunk_id": chunk.id,
                        "retrieval_mode": "keyword",
                        "matched_terms": matched_terms[:12],
                        "term_match_count": len(matched_terms),
                        "anchor_matches": anchor_matches,
                        "required_anchors": required_anchors,
                        "coverage_bucket": self._coverage_bucket(anchor_matches),
                        "content_fingerprint": content_fingerprint,
                    },
                    source_ref=chunk.source_ref,
                    score=score,
                )
                ranked.append(
                    KnowledgeSearchResult(
                        chunk_id=chunk.id,
                        content=chunk.content,
                        score=score,
                        source_ref=chunk.source_ref,
                        metadata=metadata,
                    )
                )
            ranked.sort(key=lambda item: item.score or 0, reverse=True)
            deduped = self._dedupe_by_content(ranked)
            return self._coverage_rank(deduped, required_anchors, top_k)

    def _maybe_rerank(self, results: list[KnowledgeSearchResult], top_k: int) -> list[KnowledgeSearchResult]:
        if not rerank_enabled():
            return results
        try:
            return RuleBasedReranker().rerank(results, top_k)
        except Exception:
            return results

    def _vector_search(
        self,
        course_id: int,
        query: str,
        top_k: int,
        owner_user_id: int | None = None,
    ) -> list[KnowledgeSearchResult]:
        if os.getenv("RAG_EMBEDDING_ENABLED", "").strip().lower() not in {"1", "true", "yes", "on"}:
            return []
        settings = EmbeddingSettings.from_env()
        provider = self.embedding_provider or build_embedding_provider(settings)
        if provider is None:
            return []
        try:
            return SQLiteVectorSearchService(database_url=self.database_url, provider=provider).search(
                course_id,
                query,
                top_k,
                owner_user_id=owner_user_id,
            )
        except Exception:
            return []

    def _hybrid_rank(
        self,
        keyword_results: list[KnowledgeSearchResult],
        vector_results: list[KnowledgeSearchResult],
        top_k: int,
    ) -> list[KnowledgeSearchResult]:
        keyword_weight = _float_from_env("RAG_KEYWORD_WEIGHT", 0.45)
        vector_weight = _float_from_env("RAG_VECTOR_WEIGHT", 0.55)
        keyword_max = max((item.score or 0 for item in keyword_results), default=0)
        vector_max = max((item.score or 0 for item in vector_results), default=0)
        merged: dict[int | str, KnowledgeSearchResult] = {}

        def key_for(item: KnowledgeSearchResult) -> int | str:
            return item.chunk_id if item.chunk_id is not None else item.source_ref or item.content

        def normalized(score: float | None, max_score: float) -> float:
            if not score or max_score <= 0:
                return 0.0
            return score / max_score

        for item in keyword_results:
            key = key_for(item)
            keyword_score = item.score or 0.0
            final_score = keyword_weight * normalized(keyword_score, keyword_max)
            metadata = {
                **item.metadata,
                "retrieval_mode": "hybrid",
                "keyword_score": keyword_score,
                "vector_score": 0.0,
            }
            merged[key] = item.model_copy(update={"score": round(final_score, 4), "metadata": metadata})

        for item in vector_results:
            key = key_for(item)
            vector_score = item.score or 0.0
            if key in merged:
                current = merged[key]
                keyword_score = float(current.metadata.get("keyword_score") or 0.0)
                final_score = (
                    keyword_weight * normalized(keyword_score, keyword_max)
                    + vector_weight * normalized(vector_score, vector_max)
                )
                metadata = {
                    **item.metadata,
                    **current.metadata,
                    "retrieval_mode": "hybrid",
                    "keyword_score": keyword_score,
                    "vector_score": round(vector_score, 4),
                }
                merged[key] = current.model_copy(update={"score": round(final_score, 4), "metadata": metadata})
            else:
                final_score = vector_weight * normalized(vector_score, vector_max)
                metadata = {
                    **item.metadata,
                    "retrieval_mode": "hybrid",
                    "keyword_score": 0.0,
                    "vector_score": round(vector_score, 4),
                    "matched_terms": item.metadata.get("matched_terms", []),
                    "term_match_count": item.metadata.get("term_match_count", 0),
                    "anchor_matches": item.metadata.get("anchor_matches", []),
                    "required_anchors": item.metadata.get("required_anchors", []),
                    "coverage_bucket": item.metadata.get("coverage_bucket", "general"),
                }
                merged[key] = item.model_copy(update={"score": round(final_score, 4), "metadata": metadata})

        ranked = list(merged.values())
        ranked.sort(key=lambda item: item.score or 0, reverse=True)
        return ranked[:top_k]

    def _query_terms(self, query: str) -> list[str]:
        normalized = query.strip().lower()
        if not normalized:
            return []
        raw_terms = re.findall(r"[a-z0-9#:+\-/]+|[\u4e00-\u9fff]+", normalized, flags=re.UNICODE)
        terms: list[str] = []
        for term in raw_terms:
            if len(term) < 2:
                continue
            terms.append(term)
            if re.fullmatch(r"[\u4e00-\u9fff]+", term) and len(term) > 2:
                terms.extend(term[index : index + 2] for index in range(0, len(term) - 1))
        terms.extend(self._expanded_query_terms(normalized))
        if not terms:
            compact = re.sub(r"\s+", "", normalized)
            if compact:
                terms.append(compact)
                if len(compact) > 2:
                    terms.extend(compact[index : index + 2] for index in range(0, len(compact) - 1))
        return list(dict.fromkeys(terms))

    def _score(self, haystack: str, query_terms: list[str]) -> float:
        matched_terms = self._matched_terms(haystack, query_terms)
        return self._score_from_matches(matched_terms, query_terms, haystack, [], [])

    def _matched_terms(self, haystack: str, query_terms: list[str]) -> list[str]:
        return [term for term in query_terms if term in haystack]

    def _expanded_query_terms(self, normalized_query: str) -> list[str]:
        expansions: list[str] = []
        for triggers, expanded_terms in QUERY_EXPANSIONS:
            if any(trigger in normalized_query for trigger in triggers):
                expansions.extend(triggers)
                expansions.extend(expanded_terms)
        for anchor in self._anchor_matches(normalized_query):
            expansions.extend(ANCHOR_EXPANSIONS.get(anchor, []))
        return expansions

    def _score_from_matches(
        self,
        matched_terms: list[str],
        query_terms: list[str],
        haystack: str,
        anchor_matches: list[str],
        required_anchors: list[str],
    ) -> float:
        matched = len(matched_terms)
        if matched == 0 or not query_terms:
            return 0.0
        phrase_bonus = 0.5 if " ".join(query_terms) in haystack else 0.0
        coverage = matched / len(query_terms)
        density_bonus = min(0.25, matched * 0.03)
        required_anchor_set = set(required_anchors)
        matched_anchor_set = set(anchor_matches)
        anchor_bonus = 0.0
        if required_anchor_set:
            anchor_bonus = 0.18 * len(required_anchor_set.intersection(matched_anchor_set))
            if len(required_anchor_set) >= 2 and required_anchor_set.issubset(matched_anchor_set):
                anchor_bonus += 0.25
        return round(coverage + phrase_bonus + density_bonus + anchor_bonus, 4)

    def _anchor_matches(self, text: str) -> list[str]:
        matches: list[str] = []
        for anchor, aliases in ANCHOR_TERMS.items():
            if any(alias in text for alias in aliases):
                matches.append(anchor)
        return matches

    def _coverage_bucket(self, anchor_matches: list[str]) -> str:
        anchor_set = set(anchor_matches)
        if {"bfs", "dfs"}.issubset(anchor_set):
            return "bfs_dfs_compare"
        if "bfs" in anchor_set:
            return "bfs"
        if "dfs" in anchor_set:
            return "dfs"
        return "general"

    def _content_fingerprint(self, content: str) -> str:
        return re.sub(r"\s+", "", content.lower())[:180]

    def _dedupe_by_content(self, ranked: list[KnowledgeSearchResult]) -> list[KnowledgeSearchResult]:
        deduped: list[KnowledgeSearchResult] = []
        seen_fingerprints: set[str] = set()
        for item in ranked:
            fingerprint = str(item.metadata.get("content_fingerprint") or self._content_fingerprint(item.content))
            if fingerprint in seen_fingerprints:
                continue
            seen_fingerprints.add(fingerprint)
            deduped.append(item)
        return deduped

    def _coverage_rank(
        self,
        ranked: list[KnowledgeSearchResult],
        required_anchors: list[str],
        top_k: int,
    ) -> list[KnowledgeSearchResult]:
        if len(required_anchors) < 2:
            return ranked[:top_k]

        selected: list[KnowledgeSearchResult] = []
        selected_keys: set[int | str] = set()
        required_anchor_set = set(required_anchors)

        def key_for(item: KnowledgeSearchResult) -> int | str:
            return item.chunk_id if item.chunk_id is not None else item.source_ref or item.content

        def anchors_for(item: KnowledgeSearchResult) -> set[str]:
            raw = item.metadata.get("anchor_matches", [])
            return set(raw if isinstance(raw, list) else [])

        def bucket_for(item: KnowledgeSearchResult) -> str:
            return str(item.metadata.get("coverage_bucket") or "general")

        def add(item: KnowledgeSearchResult) -> None:
            key = key_for(item)
            if key in selected_keys:
                return
            selected.append(item)
            selected_keys.add(key)

        for bucket in ["bfs_dfs_compare", "bfs", "dfs"]:
            for item in ranked:
                if bucket_for(item) == bucket:
                    add(item)
                    break

        for item in ranked:
            if required_anchor_set.issubset(anchors_for(item)):
                add(item)
                break

        for anchor in required_anchors:
            for item in ranked:
                if anchor in anchors_for(item):
                    add(item)
                    break

        for item in ranked:
            add(item)
            if len(selected) >= top_k:
                break

        return selected[:top_k]


def _retrieval_mode() -> str:
    mode = os.getenv("RAG_RETRIEVAL_MODE", "keyword").strip().lower()
    if mode not in {"keyword", "vector", "hybrid"}:
        return "keyword"
    return mode


def _float_from_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default
