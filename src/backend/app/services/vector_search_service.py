import json
import math
import os

from sqlalchemy import or_, select

from app.adapters.protocols import EmbeddingProvider
from app.db.schema_compat import ensure_document_columns
from app.db.session import session_scope
from app.models import ChunkEmbedding, Document, DocumentChunk
from app.schemas import KnowledgeSearchResult
from app.services.citation_service import build_source_metadata
from app.services.embedding_index_service import EmbeddingIndexService


class SQLiteVectorSearchService:
    def __init__(
        self,
        database_url: str | None = None,
        provider: EmbeddingProvider | None = None,
        max_candidates: int | None = None,
    ) -> None:
        self.database_url = database_url
        self.provider = provider
        self.max_candidates = max_candidates or _int_from_env("RAG_VECTOR_MAX_CANDIDATES", 1000)

    def search(
        self,
        course_id: int,
        query: str,
        top_k: int,
        owner_user_id: int | None = None,
    ) -> list[KnowledgeSearchResult]:
        if self.provider is None or top_k <= 0:
            return []
        query_vector = self.provider.embed(query).vector
        if not query_vector:
            return []

        ensure_document_columns(self.database_url)
        with session_scope(self.database_url) as session:
            statement = (
                select(DocumentChunk, ChunkEmbedding, Document)
                .join(Document, Document.id == DocumentChunk.document_id)
                .join(ChunkEmbedding, ChunkEmbedding.chunk_id == DocumentChunk.id)
                .where(Document.course_id == course_id)
                .where(Document.status != "deleted")
                .order_by(ChunkEmbedding.id.desc())
                .limit(max(1, self.max_candidates))
            )
            if owner_user_id is None:
                statement = statement.where(Document.visibility.in_(["course", "demo"]))
            else:
                statement = statement.where(
                    or_(Document.visibility.in_(["course", "demo"]), Document.owner_user_id == owner_user_id)
                )
            rows = session.execute(statement).all()

            ranked: list[KnowledgeSearchResult] = []
            for chunk, embedding, document in rows:
                if embedding.content_hash != EmbeddingIndexService.content_hash(chunk.content):
                    continue
                try:
                    vector = [float(value) for value in json.loads(embedding.embedding_json)]
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                score = cosine_similarity(query_vector, vector)
                if score <= 0:
                    continue
                metadata = build_source_metadata(
                    content=chunk.content,
                    document_title=document.title,
                    metadata={
                        **(chunk.metadata_json if isinstance(chunk.metadata_json, dict) else {}),
                        "document_id": chunk.document_id,
                        "chunk_id": chunk.id,
                        "retrieval_mode": "vector",
                        "vector_score": round(score, 4),
                        "embedding_provider": embedding.provider,
                        "embedding_model": embedding.model,
                    },
                    source_ref=chunk.source_ref,
                    score=round(score, 4),
                )
                ranked.append(
                    KnowledgeSearchResult(
                        chunk_id=chunk.id,
                        content=chunk.content,
                        score=round(score, 4),
                        source_ref=chunk.source_ref,
                        metadata=metadata,
                    )
                )

        ranked.sort(key=lambda item: item.score or 0, reverse=True)
        return ranked[:top_k]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _int_from_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default
