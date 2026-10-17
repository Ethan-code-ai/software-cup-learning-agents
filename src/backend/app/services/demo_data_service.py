from pathlib import Path

from sqlalchemy import Select, delete, func, select
from sqlalchemy.orm import Session

from app.core.enums import ProcessingStatus, ProfileType
from app.db.base import Base
from app.db.schema_compat import (
    ensure_agent_run_step_columns,
    ensure_document_columns,
    ensure_generated_resource_columns,
    ensure_learning_path_columns,
)
from app.db.session import get_engine, session_scope
from app.models import (
    AgentRun,
    AgentRunStep,
    Attempt,
    Concept,
    ConceptRelation,
    Course,
    Document,
    DocumentChunk,
    GeneratedResource,
    LearningPath,
    LearningPathItem,
    MasteryRecord,
    Quiz,
    QuizItem,
    StudentProfile,
    StudentProfileHistory,
)
from app.schemas import DocumentIngestionRequest, DemoDataLoadResponse, DemoDataStatusResponse, StudentProfileCreate
from app.seed.demo_data import (
    DEMO_CHAPTERS,
    DEMO_CHUNKS,
    DEMO_CONCEPTS,
    DEMO_COURSE,
    DEMO_DOCUMENT,
    DEMO_PROFILES,
    DEMO_RELATIONS,
)
from app.services.profile_builder import normalize_profile_dimensions
from app.services.document_ingestion_service import DocumentIngestionService


DEMO_CONCEPT_SLUGS = [concept["slug"] for concept in DEMO_CONCEPTS]
COURSE_CORPUS_VERSION = "data-structures-v1"

DEMO_PROFILE_TYPES = [
    ProfileType.weak_foundation,
    ProfileType.exam_sprint,
    ProfileType.algorithm_practice,
]


class DemoDataService:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url

    def get_status(self) -> DemoDataStatusResponse:
        self._ensure_tables()
        with session_scope(self.database_url) as session:
            return self._build_status(session)

    def load_demo_data(self) -> DemoDataLoadResponse:
        self._ensure_tables()
        with session_scope(self.database_url) as session:
            course = self._load_course_graph(session)
            self._load_profiles(session)
            self._load_document_chunks(session)
            session.flush()
            course_id = course.id
        self._load_course_corpus(course_id)
        with session_scope(self.database_url) as session:
            status = self._build_status(session)
        return DemoDataLoadResponse(
            status=ProcessingStatus.completed,
            message="Demo data loaded successfully." if status.is_loaded else "Demo data load finished with missing records.",
            demo_data=status,
        )

    def reset_user_data(self) -> DemoDataLoadResponse:
        self.load_demo_data()
        with session_scope(self.database_url) as session:
            session.execute(delete(StudentProfileHistory))
            session.execute(delete(AgentRunStep))
            session.execute(delete(AgentRun))
            session.execute(delete(GeneratedResource))
            session.execute(delete(LearningPathItem))
            session.execute(delete(LearningPath))
            session.execute(delete(QuizItem))
            session.execute(delete(Attempt))
            session.execute(delete(MasteryRecord))
            session.execute(delete(Quiz))

            for profile in session.scalars(select(StudentProfile).order_by(StudentProfile.id)).all():
                preferences = profile.preferences if isinstance(profile.preferences, dict) else {}
                if preferences.get("profile_origin") != "demo":
                    session.delete(profile)
            session.flush()
            status = self._build_status(session)
        return DemoDataLoadResponse(
            status=ProcessingStatus.completed,
            message="Demo user data reset successfully.",
            demo_data=status,
        )

    def _ensure_tables(self) -> None:
        Base.metadata.create_all(get_engine(self.database_url))
        ensure_document_columns(self.database_url)
        ensure_agent_run_step_columns(self.database_url)
        ensure_learning_path_columns(self.database_url)
        ensure_generated_resource_columns(self.database_url)

    def _load_course_graph(self, session: Session) -> Course:
        course = session.scalar(
            select(Course).where(Course.title == DEMO_COURSE["title"], Course.is_demo.is_(True))
        )
        if course is None:
            course = Course(**DEMO_COURSE)
            session.add(course)
            session.flush()

        concepts_by_slug: dict[str, Concept] = {}
        for concept_data in DEMO_CONCEPTS:
            concept = session.scalar(
                select(Concept).where(
                    Concept.course_id == course.id,
                    Concept.slug == concept_data["slug"],
                )
            )
            if concept is None:
                concept = Concept(course_id=course.id, **concept_data)
                session.add(concept)
                session.flush()
            concepts_by_slug[concept.slug] = concept

        expected_relations = {
            (
                concepts_by_slug[source_slug].id,
                concepts_by_slug[target_slug].id,
                relation_type,
            )
            for source_slug, target_slug, relation_type in DEMO_RELATIONS
        }
        concept_ids = set(session.scalars(
            select(Concept.id).where(Concept.course_id == course.id)
        ).all())
        existing_relations = session.scalars(
            select(ConceptRelation).where(
                ConceptRelation.source_concept_id.in_(concept_ids),
                ConceptRelation.target_concept_id.in_(concept_ids),
            )
        ).all()
        retained: set[tuple[int, int, str]] = set()
        for relation in existing_relations:
            key = (
                relation.source_concept_id,
                relation.target_concept_id,
                relation.relation_type,
            )
            if key not in expected_relations or key in retained:
                session.delete(relation)
            else:
                retained.add(key)
        for source_id, target_id, relation_type in expected_relations - retained:
            session.add(
                ConceptRelation(
                    source_concept_id=source_id,
                    target_concept_id=target_id,
                    relation_type=relation_type,
                )
            )
        return course

    def _load_profiles(self, session: Session) -> None:
        for profile_data in DEMO_PROFILES:
            normalized_profile = normalize_profile_dimensions(StudentProfileCreate(**profile_data))
            profile = self._find_demo_profile(session, profile_data)
            if profile is None:
                session.add(StudentProfile(**normalized_profile.model_dump()))
            else:
                profile.preferences = {
                    **normalized_profile.preferences,
                    **(profile.preferences if isinstance(profile.preferences, dict) else {}),
                }

    def _load_document_chunks(self, session: Session) -> None:
        course = self._get_demo_course(session)
        if course is None:
            course = self._load_course_graph(session)

        document = session.scalar(
            select(Document).where(Document.course_id == course.id, Document.title == DEMO_DOCUMENT["title"])
        )
        if document is None:
            document = Document(course_id=course.id, **DEMO_DOCUMENT)
            session.add(document)
            session.flush()

        concepts_by_slug = {
            concept.slug: concept
            for concept in session.scalars(select(Concept).where(Concept.course_id == course.id)).all()
        }
        for chunk_data in DEMO_CHUNKS:
            concept = concepts_by_slug[chunk_data["concept_slug"]]
            chunk = session.scalar(
                select(DocumentChunk).where(
                    DocumentChunk.document_id == document.id,
                    DocumentChunk.source_ref == chunk_data["source_ref"],
                )
            )
            if chunk is None:
                session.add(
                    DocumentChunk(
                        document_id=document.id,
                        concept_id=concept.id,
                        content=chunk_data["content"],
                        vector_ref=f"demo:{concept.slug}",
                        metadata_json={"course": DEMO_COURSE["title"], "concept_slug": concept.slug},
                        source_ref=chunk_data["source_ref"],
                    )
                )

    def _load_course_corpus(self, course_id: int) -> None:
        corpus_dir = Path(__file__).resolve().parents[4] / "data" / "course-corpus" / "data-structures"
        ingestion_service = DocumentIngestionService(database_url=self.database_url)
        for chapter in DEMO_CHAPTERS:
            file_path = corpus_dir / chapter["filename"]
            if not file_path.exists():
                raise FileNotFoundError(f"Course corpus file is missing: {file_path}")
            response = ingestion_service.ingest(
                course_id,
                DocumentIngestionRequest(
                    title=chapter["title"],
                    source_type="markdown",
                    visibility="demo",
                    content=file_path.read_text(encoding="utf-8"),
                ),
            )
            self._annotate_course_document(response.document.id, chapter)

    def _annotate_course_document(self, document_id: int, chapter: dict) -> None:
        with session_scope(self.database_url) as session:
            chunks = session.scalars(
                select(DocumentChunk)
                .where(DocumentChunk.document_id == document_id)
                .order_by(DocumentChunk.id)
            ).all()
            concept_id = session.scalar(
                select(Concept.id).where(Concept.slug == chapter["concept_slugs"][0])
            )
            for chunk in chunks:
                chunk.concept_id = concept_id
                chunk.metadata_json = {
                    **(chunk.metadata_json if isinstance(chunk.metadata_json, dict) else {}),
                    "course_corpus_version": COURSE_CORPUS_VERSION,
                    "chapter": chapter["chapter"],
                    "chapter_slug": chapter["slug"],
                    "concept_slugs": chapter["concept_slugs"],
                }

    def _build_status(self, session: Session) -> DemoDataStatusResponse:
        course = self._get_demo_course(session)
        if course is None:
            return DemoDataStatusResponse(
                is_loaded=False,
                concept_slugs=[],
                profile_types=[],
            )

        concept_slugs = [
            slug
            for slug in session.scalars(
                select(Concept.slug)
                .where(Concept.course_id == course.id, Concept.slug.in_(DEMO_CONCEPT_SLUGS))
                .order_by(Concept.id)
            ).all()
        ]
        profile_types = [
            ProfileType(profile_type)
            for profile_type in self._demo_profile_types(session)
        ]
        document_count = self._count(
            session,
            select(func.count()).select_from(Document).where(Document.course_id == course.id),
        )
        chunk_count = self._count(
            session,
            select(func.count())
            .select_from(DocumentChunk)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(Document.course_id == course.id),
        )
        is_loaded = (
            set(DEMO_CONCEPT_SLUGS).issubset(set(concept_slugs))
            and {profile.value for profile in DEMO_PROFILE_TYPES}.issubset({profile.value for profile in profile_types})
            and document_count >= len(DEMO_CHAPTERS) + 1
            and chunk_count > len(DEMO_CHUNKS)
        )
        return DemoDataStatusResponse(
            is_loaded=is_loaded,
            course_id=course.id,
            concept_slugs=concept_slugs,
            profile_types=profile_types,
            concept_count=len(concept_slugs),
            profile_count=len(profile_types),
            document_count=document_count,
            chunk_count=chunk_count,
        )

    def _get_demo_course(self, session: Session) -> Course | None:
        return session.scalar(select(Course).where(Course.title == DEMO_COURSE["title"], Course.is_demo.is_(True)))

    def _find_demo_profile(self, session: Session, profile_data: dict) -> StudentProfile | None:
        expected_key = profile_data["preferences"].get("demo_profile_key")
        profiles = session.scalars(
            select(StudentProfile).where(StudentProfile.profile_type == profile_data["profile_type"]).order_by(StudentProfile.id)
        ).all()
        for profile in profiles:
            preferences = profile.preferences if isinstance(profile.preferences, dict) else {}
            if preferences.get("demo_profile_key") == expected_key:
                return profile
        for profile in profiles:
            preferences = profile.preferences if isinstance(profile.preferences, dict) else {}
            if not preferences.get("profile_origin") and profile.goal == profile_data["goal"]:
                return profile
        return None

    def _demo_profile_types(self, session: Session) -> list[str]:
        profile_types: list[str] = []
        for profile in session.scalars(select(StudentProfile).order_by(StudentProfile.id)).all():
            preferences = profile.preferences if isinstance(profile.preferences, dict) else {}
            if preferences.get("profile_origin") == "demo" and preferences.get("demo_profile_key"):
                profile_types.append(profile.profile_type)
        return profile_types

    def _count(self, session: Session, statement: Select[tuple[int]]) -> int:
        return int(session.scalar(statement) or 0)
