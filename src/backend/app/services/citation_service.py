import re
from typing import Any

from app.schemas import KnowledgeSearchResult


DEFAULT_EXCERPT_LIMIT = 220


def build_source_metadata(
    *,
    content: str,
    document_title: str | None,
    metadata: dict[str, Any],
    source_ref: str | None,
    score: float | None,
    excerpt_limit: int = DEFAULT_EXCERPT_LIMIT,
) -> dict[str, Any]:
    excerpt = build_excerpt(content, excerpt_limit)
    source_metadata = {
        **metadata,
        "source_ref": source_ref,
        "source_title": document_title,
        "score": score,
        "excerpt": excerpt,
    }
    return source_metadata


def build_excerpt(content: str, max_length: int = DEFAULT_EXCERPT_LIMIT) -> str:
    normalized = re.sub(r"\s+", " ", content).strip()
    if not normalized:
        return ""
    if len(normalized) <= max_length:
        return normalized
    if max_length <= 3:
        return "." * max(0, max_length)
    return f"{normalized[: max(0, max_length - 3)].rstrip()}..."


def source_ref_payload(chunk: KnowledgeSearchResult) -> dict[str, Any]:
    return {
        "chunk_id": chunk.chunk_id,
        "source_ref": chunk.source_ref,
        "score": chunk.score,
        "source_title": chunk.metadata.get("source_title"),
        "excerpt": chunk.metadata.get("excerpt"),
        "retrieval_mode": chunk.metadata.get("retrieval_mode"),
        "keyword_score": chunk.metadata.get("keyword_score"),
        "vector_score": chunk.metadata.get("vector_score"),
        "rerank_score": chunk.metadata.get("rerank_score"),
        "rerank_reasons": chunk.metadata.get("rerank_reasons", []),
        "matched_terms": chunk.metadata.get("matched_terms", []),
        "anchor_matches": chunk.metadata.get("anchor_matches", []),
    }


def source_ref_summary(source_refs: list[dict[str, Any]]) -> str:
    if not source_refs:
        return "Grounded sources: none retrieved."
    details: list[str] = []
    for source in source_refs[:3]:
        source_ref = source.get("source_ref")
        if not source_ref:
            continue
        score = source.get("rerank_score") or source.get("score")
        reasons = source.get("rerank_reasons") or source.get("matched_terms") or source.get("anchor_matches") or []
        reason_text = ""
        if isinstance(reasons, list) and reasons:
            reason_text = f", reason={','.join(str(item) for item in reasons[:3])}"
        score_text = f", score={float(score):.2f}" if isinstance(score, (int, float)) else ""
        details.append(f"{source_ref}{score_text}{reason_text}")
    if not details:
        return "Grounded sources: none retrieved."
    return "Grounded sources: " + " | ".join(details)


def validate_citations(answer: str, source_refs: list[dict[str, Any]]) -> dict[str, Any]:
    allowed_ordered = list(
        dict.fromkeys(str(source.get("source_ref")) for source in source_refs if source.get("source_ref"))
    )
    allowed = set(allowed_ordered)
    citation_text = re.sub(r"```.*?```", "", answer, flags=re.DOTALL)
    explicit_document_refs = set(re.findall(r"document:\d+#chunk:\d+", citation_text))
    cited = explicit_document_refs & allowed
    fake = explicit_document_refs - allowed

    for raw_token in re.findall(r"\[([^\[\]\n]{1,200})\]", citation_text):
        token = raw_token.strip()
        if token.isdigit():
            index = int(token)
            if 1 <= index <= len(allowed_ordered):
                cited.add(allowed_ordered[index - 1])
        elif token in allowed:
            cited.add(token)
        elif _looks_like_source_ref(token):
            fake.add(token)

    missing = bool(allowed and not cited)
    return {
        "allowed_source_refs": sorted(allowed),
        "cited_source_refs": sorted(cited),
        "fake_source_refs": sorted(fake),
        "missing_citation": missing,
    }


def _looks_like_source_ref(token: str) -> bool:
    if token.startswith(("document:", "demo:", "http://", "https://")):
        return True
    return bool(re.search(r"\.(?:md|markdown|pdf|txt|docx?)#[-\w./:]+$", token, flags=re.I))
