from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(40), nullable=False)

    student_profiles: Mapped[list["StudentProfile"]] = relationship(back_populates="user")


class StudentProfile(TimestampMixin, Base):
    __tablename__ = "student_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    profile_type: Mapped[str] = mapped_column(String(80), nullable=False)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[str] = mapped_column(String(80), nullable=False)
    preferences: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    time_budget: Mapped[str] = mapped_column(String(120), nullable=False)

    user: Mapped[User | None] = relationship(back_populates="student_profiles")
    history: Mapped[list["StudentProfileHistory"]] = relationship(back_populates="profile")


class StudentProfileHistory(TimestampMixin, Base):
    __tablename__ = "student_profile_history"
    __table_args__ = (UniqueConstraint("event_key", name="uq_student_profile_history_event_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    student_profile_id: Mapped[int] = mapped_column(ForeignKey("student_profiles.id"), nullable=False)
    event_key: Mapped[str] = mapped_column(String(180), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(60), nullable=False)
    before_dimensions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    after_dimensions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    changed_dimensions: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_refs: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    agent_run_id: Mapped[int | None] = mapped_column(ForeignKey("agent_runs.id"), nullable=True)

    profile: Mapped[StudentProfile] = relationship(back_populates="history")


class Course(TimestampMixin, Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_demo: Mapped[bool] = mapped_column(default=False, nullable=False)

    concepts: Mapped[list["Concept"]] = relationship(back_populates="course")


class Concept(TimestampMixin, Base):
    __tablename__ = "concepts"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    chapter: Mapped[str | None] = mapped_column(String(120), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    difficulty: Mapped[str] = mapped_column(String(40), nullable=False)

    course: Mapped[Course] = relationship(back_populates="concepts")


class ConceptRelation(Base):
    __tablename__ = "concept_relations"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_concept_id: Mapped[int] = mapped_column(ForeignKey("concepts.id"), nullable=False)
    target_concept_id: Mapped[int] = mapped_column(ForeignKey("concepts.id"), nullable=False)
    relation_type: Mapped[str] = mapped_column(String(40), nullable=False)


class Document(TimestampMixin, Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    source_type: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    visibility: Mapped[str] = mapped_column(String(40), default="course", nullable=False)
    owner_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(160), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parser_name: Mapped[str | None] = mapped_column(String(80), nullable=True)

    chunks: Mapped[list["DocumentChunk"]] = relationship(back_populates="document")


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), nullable=False)
    concept_id: Mapped[int | None] = mapped_column(ForeignKey("concepts.id"), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    vector_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict, nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)

    document: Mapped[Document] = relationship(back_populates="chunks")


class ChunkEmbedding(Base):
    __tablename__ = "chunk_embeddings"
    __table_args__ = (UniqueConstraint("chunk_id", "provider", "model", "content_hash"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    chunk_id: Mapped[int] = mapped_column(ForeignKey("document_chunks.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    embedding_json: Mapped[str] = mapped_column(Text, nullable=False)
    dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    chunk: Mapped[DocumentChunk] = relationship()


class LearningPath(TimestampMixin, Base):
    __tablename__ = "learning_paths"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_profile_id: Mapped[int] = mapped_column(ForeignKey("student_profiles.id"), nullable=False)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), nullable=False)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    learning_intent: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    target_concept_ids: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    intent_confidence: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    milestones: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)

    items: Mapped[list["LearningPathItem"]] = relationship(back_populates="path")


class LearningPathItem(Base):
    __tablename__ = "learning_path_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    path_id: Mapped[int] = mapped_column(ForeignKey("learning_paths.id"), nullable=False)
    concept_id: Mapped[int] = mapped_column(ForeignKey("concepts.id"), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    node_role: Mapped[str] = mapped_column(String(40), default="target", nullable=False)
    activity_type: Mapped[str] = mapped_column(String(80), default="explanation", nullable=False)
    estimated_minutes: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    success_criterion: Mapped[str] = mapped_column(Text, default="能够完成本节点学习目标。", nullable=False)

    path: Mapped[LearningPath] = relationship(back_populates="items")


class LearningPathRecommendation(TimestampMixin, Base):
    __tablename__ = "learning_path_recommendations"
    __table_args__ = (UniqueConstraint("path_item_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    path_item_id: Mapped[int] = mapped_column(ForeignKey("learning_path_items.id"), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    execution_mode: Mapped[str] = mapped_column(String(40), nullable=False)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    fallback_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fallback_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class GeneratedResource(TimestampMixin, Base):
    __tablename__ = "generated_resources"

    id: Mapped[int] = mapped_column(primary_key=True)
    path_item_id: Mapped[int] = mapped_column(ForeignKey("learning_path_items.id"), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_refs: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    animation_spec: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class Quiz(TimestampMixin, Base):
    __tablename__ = "quizzes"

    id: Mapped[int] = mapped_column(primary_key=True)
    concept_id: Mapped[int] = mapped_column(ForeignKey("concepts.id"), nullable=False)
    student_profile_id: Mapped[int] = mapped_column(ForeignKey("student_profiles.id"), nullable=False)
    difficulty: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)


class QuizItem(Base):
    __tablename__ = "quiz_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    quiz_id: Mapped[int] = mapped_column(ForeignKey("quizzes.id"), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    difficulty: Mapped[str] = mapped_column(String(40), nullable=False)
    concept_tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)


class QuizItemGenerationMetadata(TimestampMixin, Base):
    __tablename__ = "quiz_item_generation_metadata"
    __table_args__ = (UniqueConstraint("quiz_item_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    quiz_item_id: Mapped[int] = mapped_column(ForeignKey("quiz_items.id"), nullable=False)
    question_type: Mapped[str] = mapped_column(String(40), nullable=False)
    options: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    source_refs: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    execution_mode: Mapped[str] = mapped_column(String(40), nullable=False)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    fallback_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fallback_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Attempt(TimestampMixin, Base):
    __tablename__ = "attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    quiz_id: Mapped[int] = mapped_column(ForeignKey("quizzes.id"), nullable=False)
    student_profile_id: Mapped[int] = mapped_column(ForeignKey("student_profiles.id"), nullable=False)
    answers: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)


class MasteryRecord(TimestampMixin, Base):
    __tablename__ = "mastery_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_profile_id: Mapped[int] = mapped_column(ForeignKey("student_profiles.id"), nullable=False)
    concept_id: Mapped[int] = mapped_column(ForeignKey("concepts.id"), nullable=False)
    mastery_score: Mapped[float] = mapped_column(Float, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class Task(TimestampMixin, Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_type: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    result_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_type: Mapped[str] = mapped_column(String(80), nullable=False)
    student_profile_id: Mapped[int | None] = mapped_column(ForeignKey("student_profiles.id"), nullable=True)
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    input_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    steps: Mapped[list["AgentRunStep"]] = relationship(back_populates="agent_run")


class AgentRunStep(Base):
    __tablename__ = "agent_run_steps"

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_run_id: Mapped[int] = mapped_column(ForeignKey("agent_runs.id"), nullable=False)
    agent_type: Mapped[str] = mapped_column(String(80), nullable=False)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    input_summary: Mapped[str] = mapped_column(Text, nullable=False)
    output_summary: Mapped[str] = mapped_column(Text, nullable=False)
    decision_basis: Mapped[str] = mapped_column(Text, nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    execution_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    agent_run: Mapped[AgentRun] = relationship(back_populates="steps")
