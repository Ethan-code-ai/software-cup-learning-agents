import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.document_parser import build_document_parser, infer_source_type
from app.adapters.embedding_provider import EmbeddingSettings, build_embedding_provider
from app.core.enums import ProcessingStatus
from app.db.base import Base
from app.db.schema_compat import ensure_document_columns
from app.db.session import get_engine, session_scope
from app.domain.exceptions import NotFoundError
from app.models import Course, Document, DocumentChunk
from app.schemas import DocumentChunkResponse, DocumentIngestionRequest, DocumentIngestionResponse, DocumentResponse
from app.services.chunking_service import ChunkingService
from app.services.embedding_index_service import EmbeddingIndexService


class DocumentIngestionService:
    MAX_TEXT_BYTES = 1 * 1024 * 1024
    MAX_FILE_BYTES = 5 * 1024 * 1024
    VALID_VISIBILITIES = {"course", "demo", "private"}

    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url
        self.chunker = ChunkingService()

    def ingest(self, course_id: int, payload: DocumentIngestionRequest) -> DocumentIngestionResponse:
        normalized_source_type = self._normalized_source_type(payload.source_type)
        if normalized_source_type not in {"text", "markdown"}:
            raise ValueError("JSON paste ingestion only supports text or markdown. Use file upload for PDF, Word, PPTX, spreadsheets, code files or subtitles.")
        encoded_size = len(payload.content.encode("utf-8"))
        if encoded_size > self.MAX_TEXT_BYTES:
            raise ValueError("Text or markdown document is too large. The current limit is 1 MB.")

        parser = build_document_parser(payload.source_type)
        sections = parser.parse_content(payload.content)
        return self._ingest_sections(
            course_id=course_id,
            title=payload.title,
            source_type=normalized_source_type,
            parser_name=parser.parser_name,
            sections=sections,
            visibility=payload.visibility,
            owner_user_id=payload.owner_user_id,
            file_name=payload.title,
            mime_type=None,
            file_size=encoded_size,
        )

    def ingest_upload(
        self,
        course_id: int,
        *,
        filename: str,
        content_type: str | None,
        content: bytes,
        title: str | None = None,
        visibility: str = "course",
        owner_user_id: int | None = None,
    ) -> DocumentIngestionResponse:
        if len(content) > self.MAX_FILE_BYTES:
            raise ValueError("Uploaded file is too large. The current limit is 5 MB.")
        source_type = infer_source_type(filename, content_type)
        if source_type in {"text", "markdown", "text/plain", "text/markdown"} and len(content) > self.MAX_TEXT_BYTES:
            raise ValueError("Text or markdown document is too large. The current limit is 1 MB.")

        parser = build_document_parser(source_type)
        sections = parser.parse_bytes(content, filename=filename)
        return self._ingest_sections(
            course_id=course_id,
            title=(title or filename).strip(),
            source_type=self._normalized_source_type(source_type),
            parser_name=parser.parser_name,
            sections=sections,
            visibility=visibility,
            owner_user_id=owner_user_id,
            file_name=filename,
            mime_type=content_type,
            file_size=len(content),
        )

    def list_chunks(self, document_id: int) -> list[DocumentChunkResponse]:
        self._ensure_schema()
        with session_scope(self.database_url) as session:
            document = session.get(Document, document_id)
            if document is None or document.status != ProcessingStatus.completed:
                raise NotFoundError("Document", document_id)
            chunks = session.scalars(
                select(DocumentChunk).where(DocumentChunk.document_id == document_id).order_by(DocumentChunk.id)
            ).all()
            return [self._chunk_response(chunk) for chunk in chunks]

    def _ingest_sections(
        self,
        *,
        course_id: int,
        title: str,
        source_type: str,
        parser_name: str,
        sections: list[str],
        visibility: str,
        owner_user_id: int | None,
        file_name: str | None,
        mime_type: str | None,
        file_size: int | None,
    ) -> DocumentIngestionResponse:
        chunks = self.chunker.chunk(sections)
        if not chunks:
            raise ValueError("Document content produced no chunks.")

        clean_title = title.strip() or (file_name or "uploaded-document")
        clean_visibility = self._normalized_visibility(visibility, owner_user_id)

        self._ensure_schema()
        with session_scope(self.database_url) as session:
            course = session.get(Course, course_id)
            if course is None:
                raise NotFoundError("Course", course_id)

            duplicate = self._find_duplicate_document(
                session,
                course_id=course_id,
                title=clean_title,
                source_type=source_type,
                visibility=clean_visibility,
                owner_user_id=owner_user_id,
                chunk_contents=[chunk.content for chunk in chunks],
            )
            if duplicate is not None:
                duplicate.status = ProcessingStatus.completed
                duplicate.visibility = clean_visibility
                duplicate.owner_user_id = owner_user_id
                duplicate.file_name = file_name
                duplicate.mime_type = mime_type
                duplicate.file_size = file_size
                duplicate.parser_name = parser_name
                duplicate_chunks = session.scalars(
                    select(DocumentChunk).where(DocumentChunk.document_id == duplicate.id).order_by(DocumentChunk.id)
                ).all()
                document_response = DocumentResponse.model_validate(duplicate)
                chunk_responses = [self._chunk_response(chunk) for chunk in duplicate_chunks]
                return DocumentIngestionResponse(
                    document=document_response,
                    chunks=chunk_responses,
                    chunk_count=len(chunk_responses),
                )

            document = Document(
                course_id=course_id,
                title=clean_title,
                source_type=source_type,
                status=ProcessingStatus.completed,
                visibility=clean_visibility,
                owner_user_id=owner_user_id,
                file_name=file_name,
                mime_type=mime_type,
                file_size=file_size,
                parser_name=parser_name,
            )
            session.add(document)
            session.flush()

            chunk_models: list[DocumentChunk] = []
            for index, chunk in enumerate(chunks):
                source_ref = f"document:{document.id}#chunk:{index}"
                model = DocumentChunk(
                    document_id=document.id,
                    concept_id=None,
                    content=chunk.content,
                    vector_ref=None,
                    metadata_json={
                        "chunk_index": index,
                        "filename": file_name or clean_title,
                        "parser": parser_name,
                        "char_start": chunk.char_start,
                        "char_end": chunk.char_end,
                        "document_id": document.id,
                        "source_ref": source_ref,
                        "retrieval_mode": "keyword",
                        "visibility": clean_visibility,
                        "owner_user_id": owner_user_id,
                        "mime_type": mime_type,
                        "file_size": file_size,
                    },
                    source_ref=source_ref,
                )
                session.add(model)
                chunk_models.append(model)
            session.flush()

            document_response = DocumentResponse.model_validate(document)
            chunk_responses = [self._chunk_response(chunk) for chunk in chunk_models]

        self._maybe_index_embeddings(course_id)
        return DocumentIngestionResponse(
            document=document_response,
            chunks=chunk_responses,
            chunk_count=len(chunk_responses),
        )

    def _chunk_response(self, chunk: DocumentChunk) -> DocumentChunkResponse:
        return DocumentChunkResponse(
            id=chunk.id,
            document_id=chunk.document_id,
            concept_id=chunk.concept_id,
            content=chunk.content,
            vector_ref=chunk.vector_ref,
            metadata=chunk.metadata_json,
            source_ref=chunk.source_ref,
        )

    def _maybe_index_embeddings(self, course_id: int) -> None:
        if os.getenv("RAG_EMBEDDING_ENABLED", "").strip().lower() not in {"1", "true", "yes", "on"}:
            return
        settings = EmbeddingSettings.from_env()
        provider = build_embedding_provider(settings)
        if provider is None:
            return
        EmbeddingIndexService(
            database_url=self.database_url,
            provider=provider,
            provider_name=settings.provider or "configured",
            model=settings.model or "configured",
        ).index_course(course_id)

    def _find_duplicate_document(
        self,
        session: Session,
        *,
        course_id: int,
        title: str,
        source_type: str,
        visibility: str,
        owner_user_id: int | None,
        chunk_contents: list[str],
    ) -> Document | None:
        statement = (
            select(Document)
            .where(Document.course_id == course_id)
            .where(Document.title == title)
            .where(Document.source_type == source_type)
            .where(Document.visibility == visibility)
            .order_by(Document.id.desc())
        )
        if visibility == "private":
            statement = statement.where(Document.owner_user_id == owner_user_id)
        candidates = session.scalars(statement).all()
        for document in candidates:
            existing_chunks = session.scalars(
                select(DocumentChunk).where(DocumentChunk.document_id == document.id).order_by(DocumentChunk.id)
            ).all()
            if [chunk.content for chunk in existing_chunks] == chunk_contents:
                return document
        return None

    def _normalized_visibility(self, visibility: str, owner_user_id: int | None) -> str:
        normalized = (visibility or "course").strip().lower()
        if normalized not in self.VALID_VISIBILITIES:
            raise ValueError("visibility must be one of: course, demo, private.")
        if normalized == "private" and owner_user_id is None:
            raise ValueError("owner_user_id is required for private documents.")
        return normalized

    def _normalized_source_type(self, source_type: str) -> str:
        normalized = source_type.strip().lower()
        if normalized in {"text/plain", "txt", "plain_text"}:
            return "text"
        if normalized in {"text/markdown", "md"}:
            return "markdown"
        if normalized in {"application/pdf"}:
            return "pdf"
        if normalized in {"application/vnd.openxmlformats-officedocument.wordprocessingml.document", "word"}:
            return "docx"
        if normalized in {"application/vnd.openxmlformats-officedocument.presentationml.presentation", "powerpoint"}:
            return "pptx"
        if normalized in {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "spreadsheet"}:
            return "xlsx"
        if normalized in {"text/csv"}:
            return "csv"
        if normalized in {"application/x-ipynb+json", "notebook"}:
            return "ipynb"
        if normalized in {"text/vtt", "subtitle"}:
            return "vtt"
        if normalized.startswith("text/x-"):
            return "code"
        return normalized

    def _ensure_schema(self) -> None:
        Base.metadata.create_all(get_engine(self.database_url))
        ensure_document_columns(self.database_url)
