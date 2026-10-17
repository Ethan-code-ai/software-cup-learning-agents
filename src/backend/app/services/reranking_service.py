import os

from app.schemas import KnowledgeSearchResult


class RuleBasedReranker:
    def __init__(self, max_candidates: int | None = None, top_context: int | None = None, char_limit: int | None = None) -> None:
        self.max_candidates = max_candidates or _int_from_env("RAG_RERANK_MAX_CANDIDATES", 12)
        self.top_context = top_context or _int_from_env("RAG_RERANK_TOP_CONTEXT", 5)
        self.char_limit = char_limit or _int_from_env("RAG_RERANK_CONTEXT_CHAR_LIMIT", 3500)

    def rerank(self, results: list[KnowledgeSearchResult], top_k: int) -> list[KnowledgeSearchResult]:
        if not results:
            return []
        candidates = results[: max(1, self.max_candidates)]
        max_score = max((item.score or 0 for item in candidates), default=0)
        reranked: list[KnowledgeSearchResult] = []
        seen_sources: set[str] = set()

        for item in candidates:
            score, reasons = self._score_item(item, max_score, seen_sources)
            source_key = str(item.metadata.get("document_id") or item.source_ref or item.chunk_id)
            seen_sources.add(source_key)
            metadata = {
                **item.metadata,
                "rerank_score": round(score, 4),
                "rerank_reasons": reasons,
            }
            reranked.append(item.model_copy(update={"score": round(score, 4), "metadata": metadata}))

        reranked.sort(key=lambda item: item.metadata.get("rerank_score", item.score or 0), reverse=True)
        return self._apply_context_budget(reranked, top_k)

    def _score_item(self, item: KnowledgeSearchResult, max_score: float, seen_sources: set[str]) -> tuple[float, list[str]]:
        reasons: list[str] = []
        normalized_score = (item.score or 0) / max_score if max_score > 0 else 0.0
        score = 0.45 * normalized_score
        if normalized_score > 0:
            reasons.append("retrieval_score")

        anchor_matches = _as_list(item.metadata.get("anchor_matches"))
        required_anchors = _as_list(item.metadata.get("required_anchors"))
        if required_anchors:
            covered = set(anchor_matches).intersection(required_anchors)
            score += 0.25 * (len(covered) / max(1, len(required_anchors)))
            reasons.extend(f"covers_required_anchor:{anchor}" for anchor in sorted(covered))
        elif anchor_matches:
            score += 0.12
            reasons.append("anchor_match")

        if item.metadata.get("coverage_bucket") == "bfs_dfs_compare":
            score += 0.08
            reasons.append("compare_chunk")

        source_key = str(item.metadata.get("document_id") or item.source_ref or item.chunk_id)
        if source_key not in seen_sources:
            score += 0.10
            reasons.append("source_diversity_bonus")

        if item.metadata.get("concept_slug") or item.metadata.get("concept_id"):
            score += 0.10
            reasons.append("concept_alignment")

        length = len(item.content)
        if 80 <= length <= 900:
            score += 0.10
            reasons.append("concise_context")
        elif length > 1200:
            score -= 0.08
            reasons.append("long_chunk_penalty")

        return max(0.0, score), reasons

    def _apply_context_budget(self, results: list[KnowledgeSearchResult], top_k: int) -> list[KnowledgeSearchResult]:
        selected: list[KnowledgeSearchResult] = []
        total_chars = 0
        limit = max(1, min(top_k, self.top_context))
        for item in results:
            if len(selected) >= limit:
                break
            next_total = total_chars + len(item.content)
            if selected and next_total > self.char_limit:
                continue
            selected.append(item)
            total_chars = next_total
        return selected


def rerank_enabled() -> bool:
    return os.getenv("RAG_RERANK_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}


def _as_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _int_from_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default
