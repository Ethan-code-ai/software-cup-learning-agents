import inspect
import unittest

from app.main import create_app
from app.models import Base
from app.adapters.protocols import ImageGenerationResult
from app.schemas import DemoDataStatusResponse, LearningPathCreate, StudentProfileCreate
from app.services import (
    agent_run_service,
    assessment_service,
    course_service,
    knowledge_base_service,
    learning_path_service,
    document_ingestion_service,
    profile_service,
    profile_updater_service,
    resource_service,
    tutor_service,
)


class BackendContractTests(unittest.TestCase):
    def test_required_tables_are_declared(self) -> None:
        expected_tables = {
            "users",
            "student_profiles",
            "courses",
            "concepts",
            "concept_relations",
            "documents",
            "document_chunks",
            "chunk_embeddings",
            "learning_paths",
            "learning_path_items",
            "generated_resources",
            "quizzes",
            "quiz_items",
            "attempts",
            "mastery_records",
            "tasks",
            "agent_runs",
            "agent_run_steps",
        }
        self.assertTrue(expected_tables.issubset(set(Base.metadata.tables)))

    def test_schema_objects_are_constructible(self) -> None:
        profile = StudentProfileCreate(
            profile_type="weak_foundation",
            goal="补齐链表和树遍历基础",
            level="beginner",
            preferences={"style": "step_by_step"},
            time_budget="每天 1 小时",
        )
        path = LearningPathCreate(
            student_profile_id=1,
            course_id=1,
            goal="准备数据结构小测",
        )
        status = DemoDataStatusResponse(
            is_loaded=False,
            concept_slugs=["complexity-analysis"],
            profile_types=["weak_foundation"],
        )
        self.assertEqual(profile.profile_type, "weak_foundation")
        self.assertEqual(path.course_id, 1)
        self.assertFalse(status.is_loaded)

    def test_image_generation_result_contract_is_constructible(self) -> None:
        result = ImageGenerationResult(
            image_url=None,
            image_bytes=None,
            mime_type="image/png",
            metadata={"provider": "future"},
        )
        self.assertEqual(result.mime_type, "image/png")
        self.assertEqual(result.metadata["provider"], "future")

    def test_api_prefix_and_demo_routes_exist(self) -> None:
        app = create_app()
        paths = {route.path for route in app.routes}
        self.assertIn("/api/v1/demo-data/status", paths)
        self.assertIn("/api/v1/demo-data/load", paths)

    def test_domain_services_do_not_import_external_adapter_details(self) -> None:
        service_modules = [
            agent_run_service,
            assessment_service,
            course_service,
            document_ingestion_service,
            knowledge_base_service,
            learning_path_service,
            profile_service,
            profile_updater_service,
            resource_service,
            tutor_service,
        ]
        forbidden_tokens = ("openai", "chroma", "redis", "rq", "fastapi", "httpexception")
        for module in service_modules:
            source = inspect.getsource(module).lower()
            for token in forbidden_tokens:
                self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
