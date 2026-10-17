from sqlalchemy import delete, select

from app.db.session import session_scope
from app.domain.exceptions import NotFoundError, ProtectedResourceError
from app.models import (
    AgentRun,
    AgentRunStep,
    Attempt,
    GeneratedResource,
    LearningPath,
    LearningPathItem,
    LearningPathRecommendation,
    MasteryRecord,
    Quiz,
    QuizItem,
    QuizItemGenerationMetadata,
    StudentProfile,
    StudentProfileHistory,
)
from app.schemas import StudentProfileCreate, StudentProfileDialogueCreate, StudentProfileResponse
from app.agents.profile_builder_agents import build_profile_builder_agent
from app.services.profile_builder import normalize_profile_dimensions
from app.services.demo_data_service import DemoDataService
from app.services.profile_updater_service import ProfileUpdaterService


class ProfileService:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url

    def get_profile(self, profile_id: int) -> StudentProfileResponse:
        DemoDataService(database_url=self.database_url).load_demo_data()
        with session_scope(self.database_url) as session:
            profile = session.get(StudentProfile, profile_id)
            if profile is None:
                raise NotFoundError("Student profile", profile_id)
            return StudentProfileResponse.model_validate(profile)

    def list_demo_profiles(self) -> list[StudentProfileResponse]:
        DemoDataService(database_url=self.database_url).load_demo_data()
        with session_scope(self.database_url) as session:
            profiles = session.scalars(select(StudentProfile).order_by(StudentProfile.id)).all()
            return [StudentProfileResponse.model_validate(profile) for profile in profiles]

    def create_profile(self, payload: StudentProfileCreate) -> StudentProfileResponse:
        DemoDataService(database_url=self.database_url).get_status()
        normalized_payload = normalize_profile_dimensions(payload)
        with session_scope(self.database_url) as session:
            profile = StudentProfile(**normalized_payload.model_dump())
            session.add(profile)
            session.flush()
            return StudentProfileResponse.model_validate(profile)

    def create_profile_from_dialogue(self, payload: StudentProfileDialogueCreate) -> StudentProfileResponse:
        result = build_profile_builder_agent().build(payload)
        profile = self.create_profile(result.profile)
        ProfileUpdaterService(database_url=self.database_url).create_initial_history(
            profile.id,
            evidence_summary=result.evidence_summary,
            execution_mode=result.execution_mode,
            provider=result.provider,
            model=result.model,
            fallback_reason=result.fallback_reason,
            duration_ms=result.duration_ms,
        )
        return profile

    def list_profile_history(self, profile_id: int, limit: int = 20):
        return ProfileUpdaterService(database_url=self.database_url).list_history(profile_id, limit)

    def delete_profile(self, profile_id: int) -> None:
        DemoDataService(database_url=self.database_url).get_status()
        with session_scope(self.database_url) as session:
            profile = session.get(StudentProfile, profile_id)
            if profile is None:
                raise NotFoundError("Student profile", profile_id)
            preferences = profile.preferences if isinstance(profile.preferences, dict) else {}
            if preferences.get("profile_origin") == "demo":
                raise ProtectedResourceError("Demo student profiles cannot be deleted.")

            path_ids = [
                row[0]
                for row in session.execute(select(LearningPath.id).where(LearningPath.student_profile_id == profile_id)).all()
            ]
            item_ids: list[int] = []
            if path_ids:
                item_ids = [
                    row[0]
                    for row in session.execute(select(LearningPathItem.id).where(LearningPathItem.path_id.in_(path_ids))).all()
                ]
            quiz_ids = [
                row[0]
                for row in session.execute(select(Quiz.id).where(Quiz.student_profile_id == profile_id)).all()
            ]
            quiz_item_ids: list[int] = []
            if quiz_ids:
                quiz_item_ids = [
                    row[0]
                    for row in session.execute(select(QuizItem.id).where(QuizItem.quiz_id.in_(quiz_ids))).all()
                ]
            run_ids = [
                row[0]
                for row in session.execute(select(AgentRun.id).where(AgentRun.student_profile_id == profile_id)).all()
            ]

            if item_ids:
                session.execute(delete(LearningPathRecommendation).where(LearningPathRecommendation.path_item_id.in_(item_ids)))
                session.execute(delete(GeneratedResource).where(GeneratedResource.path_item_id.in_(item_ids)))
            if path_ids:
                session.execute(delete(LearningPathItem).where(LearningPathItem.path_id.in_(path_ids)))
                session.execute(delete(LearningPath).where(LearningPath.id.in_(path_ids)))
            if quiz_ids:
                if quiz_item_ids:
                    session.execute(
                        delete(QuizItemGenerationMetadata).where(
                            QuizItemGenerationMetadata.quiz_item_id.in_(quiz_item_ids)
                        )
                    )
                session.execute(delete(QuizItem).where(QuizItem.quiz_id.in_(quiz_ids)))
                session.execute(delete(Attempt).where(Attempt.quiz_id.in_(quiz_ids)))
                session.execute(delete(Quiz).where(Quiz.id.in_(quiz_ids)))
            session.execute(delete(Attempt).where(Attempt.student_profile_id == profile_id))
            session.execute(delete(MasteryRecord).where(MasteryRecord.student_profile_id == profile_id))
            session.execute(delete(StudentProfileHistory).where(StudentProfileHistory.student_profile_id == profile_id))
            if run_ids:
                session.execute(delete(AgentRunStep).where(AgentRunStep.agent_run_id.in_(run_ids)))
                session.execute(delete(AgentRun).where(AgentRun.id.in_(run_ids)))
            session.delete(profile)
