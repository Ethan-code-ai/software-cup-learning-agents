from enum import StrEnum


class UserRole(StrEnum):
    student = "student"
    teacher = "teacher"
    admin = "admin"


class ProfileType(StrEnum):
    weak_foundation = "weak_foundation"
    exam_sprint = "exam_sprint"
    algorithm_practice = "algorithm_practice"


class RelationType(StrEnum):
    prerequisite = "prerequisite"
    related = "related"
    contains = "contains"


class ProcessingStatus(StrEnum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    deleted = "deleted"


class LearningPathStatus(StrEnum):
    draft = "draft"
    active = "active"
    completed = "completed"


class LearningPathItemStatus(StrEnum):
    pending = "pending"
    in_progress = "in_progress"
    completed = "completed"


class AgentType(StrEnum):
    router = "router"
    retriever = "retriever"
    profile_builder = "profile_builder"
    profile_updater = "profile_updater"
    planner = "planner"
    resource = "resource"
    tutor = "tutor"
    quiz = "quiz"
    evaluator = "evaluator"


class AgentRunStatus(StrEnum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class TaskType(StrEnum):
    document_ingestion = "document_ingestion"
    resource_generation = "resource_generation"
    quiz_generation = "quiz_generation"
    learning_flow = "learning_flow"
