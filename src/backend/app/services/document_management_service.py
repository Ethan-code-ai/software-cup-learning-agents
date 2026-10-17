from sqlalchemy import func, select

from app.core.enums import ProcessingStatus
from app.db.base import Base
from app.db.schema_compat import ensure_document_columns
from app.db.session import get_engine, session_scope
from app.domain.exceptions import NotFoundError, ProtectedResourceError
from app.models import Course, Document, DocumentChunk
from app.schemas import DocumentManagementResponse, DocumentReindexResponse
from app.adapters.embedding_provider import EmbeddingSettings, build_embedding_provider
from app.services.embedding_index_service import EmbeddingIndexService


class DocumentManagementService:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url

    def list_course_documents(self, course_id: int) -> list[DocumentManagementResponse]:
        self._ensure_schema()
        with session_scope(self.database_url) as session:
            course = session.get(Course, course_id)
            if course is None:
                raise NotFoundError("Course", course_id)

            rows = session.execute(
                select(Document, func.count(DocumentChunk.id))
                .outerjoin(DocumentChunk, DocumentChunk.document_id == Document.id)
                .where(Document.course_id == course_id)
                .where(Document.status != ProcessingStatus.deleted)
                .group_by(Document.id)
                .order_by(Document.id.desc())
            ).all()
            return [self._document_response(document, chunk_count) for document, chunk_count in rows]

    def get_document(self, document_id: int) -> DocumentManagementResponse:
        self._ensure_schema()
        with session_scope(self.database_url) as session:
            row = session.execute(
                select(Document, func.count(DocumentChunk.id))
                .outerjoin(DocumentChunk, DocumentChunk.document_id == Document.id)
                .where(Document.id == document_id)
                .group_by(Document.id)
            ).first()
            if row is None:
                raise NotFoundError("Document", document_id)
            document, chunk_count = row
            return self._document_response(document, chunk_count)

    def delete_document(self, document_id: int) -> None:
        self._ensure_schema()
        with session_scope(self.database_url) as session:
            document = session.get(Document, document_id)
            if document is None:
                raise NotFoundError("Document", document_id)
            if document.source_type == "seed":
                raise ProtectedResourceError("Demo seed documents cannot be deleted.")
            document.status = ProcessingStatus.deleted

    def reindex_document(self, document_id: int) -> DocumentReindexResponse:
        self._ensure_schema()
        with session_scope(self.database_url) as session:
            document = session.get(Document, document_id)
            if document is None or document.status == ProcessingStatus.deleted:
                raise NotFoundError("Document", document_id)

        settings = EmbeddingSettings.from_env()
        if not settings.enabled:
            return DocumentReindexResponse(
                document_id=document_id,
                indexed=0,
                skipped=0,
                failed=0,
                enabled=False,
                message="Embedding is disabled. Keyword retrieval remains available.",
            )
        provider = build_embedding_provider(settings)
        if provider is None:
            return DocumentReindexResponse(
                document_id=document_id,
                indexed=0,
                skipped=0,
                failed=0,
                enabled=False,
                message="Embedding provider is not configured. Keyword retrieval remains available.",
            )

        result = EmbeddingIndexService(
            database_url=self.database_url,
            provider=provider,
            provider_name=settings.provider or "configured",
            model=settings.model or "configured",
        ).index_document(document_id)
        return DocumentReindexResponse(
            document_id=document_id,
            indexed=result.indexed,
            skipped=result.skipped,
            failed=result.failed,
            enabled=True,
            message="Document reindex finished. Keyword retrieval remains available if embedding fails.",
        )

    def _document_response(self, document: Document, chunk_count: int) -> DocumentManagementResponse:
        return DocumentManagementResponse(
            id=document.id,
            course_id=document.course_id,
            title=document.title,
            source_type=document.source_type,
            status=document.status,
            created_at=document.created_at,
            visibility=document.visibility,
            owner_user_id=document.owner_user_id,
            file_name=document.file_name,
            mime_type=document.mime_type,
            file_size=document.file_size,
            parser_name=document.parser_name,
            chunk_count=int(chunk_count or 0),
        )

    def _ensure_schema(self) -> None:
        Base.metadata.create_all(get_engine(self.database_url))
        ensure_document_columns(self.database_url)
