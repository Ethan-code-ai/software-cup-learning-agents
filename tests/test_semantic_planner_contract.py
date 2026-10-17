import unittest
import os
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.agents.planner_agents import (
    GoalResolutionError,
    LearningIntent,
    PlannerConcept,
    PlannerContext,
    PlannerRelation,
    resolve_goal_deterministically,
    select_minimal_path,
)
from app.db.session import get_engine, session_scope
from app.main import create_app
from app.models import Concept, ConceptRelation, LearningPath
from app.services.demo_data_service import DemoDataService


class SemanticPlannerContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.concepts = [
            PlannerConcept(1, "stack", "栈", "线性结构", "basic"),
            PlannerConcept(2, "queue", "队列", "线性结构", "basic"),
            PlannerConcept(3, "graph-representation", "图的表示", "图", "basic"),
            PlannerConcept(4, "bfs-dfs", "BFS/DFS", "图", "medium"),
            PlannerConcept(5, "shortest-path", "最短路径", "图", "medium"),
            PlannerConcept(6, "hash-table", "哈希表", "查找", "medium"),
        ]
        self.context = PlannerContext(
            goal="",
            profile_type="exam_sprint",
            foundation_level="intermediate",
            learning_preference="summary_first",
            available_time="每天两小时",
            weak_points=[],
            resource_preference="练习题",
        )

    def test_bfs_dfs_synonyms_resolve_to_same_target_and_quiz_intent(self) -> None:
        target_sets = []
        for goal in ("图搜索", "深度搜索和广度搜索", "BFS/DFS", "广搜和深搜"):
            resolution = resolve_goal_deterministically(goal, self.concepts)
            target_sets.append(set(resolution.target_concept_ids))
        self.assertTrue(all(targets == {4} for targets in target_sets))

        quiz = resolve_goal_deterministically("巩固 BFS/DFS，为课程小测做准备", self.concepts)
        self.assertEqual(quiz.learning_intent.purpose, "assessment_preparation")
        self.assertEqual(quiz.learning_intent.assessment_type, "course_quiz")

    def test_unknown_goal_is_rejected_instead_of_expanding_to_full_course(self) -> None:
        with self.assertRaises(GoalResolutionError):
            resolve_goal_deterministically("把这个再弄扎实一点", self.concepts)

    def test_minimal_path_adds_only_unsatisfied_hard_prerequisites(self) -> None:
        intent = LearningIntent(
            purpose="concept_learning",
            action="learn",
            assessment_type="none",
            time_horizon="short_term",
            preferred_activities=["explanation"],
            desired_outcome="掌握 BFS 与 DFS",
        )
        selected = select_minimal_path(
            self.concepts,
            [PlannerRelation(3, 4, "prerequisite"), PlannerRelation(2, 4, "related")],
            target_concept_ids=[4],
            optional_support_concept_ids=[],
            context=self.context,
            learning_intent=intent,
        )
        self.assertEqual([item.concept.id for item in selected], [3, 4])
        self.assertEqual([item.node_role for item in selected], ["prerequisite", "target"])

        mastered_context = PlannerContext(**{**self.context.__dict__, "mastery_scores": {3: 0.8}})
        selected = select_minimal_path(
            self.concepts,
            [PlannerRelation(3, 4, "prerequisite")],
            target_concept_ids=[4],
            optional_support_concept_ids=[],
            context=mastered_context,
            learning_intent=intent,
        )
        self.assertEqual([item.concept.id for item in selected], [4])


class SemanticPlannerApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        path = Path(self.temp_dir.name) / "semantic-planner.sqlite3"
        self.database_url = f"sqlite:///{path.as_posix()}"
        os.environ["APP_DATABASE_URL"] = self.database_url

    def tearDown(self) -> None:
        get_engine().dispose()
        get_engine(self.database_url).dispose()
        get_engine.cache_clear()
        os.environ.pop("APP_DATABASE_URL", None)
        self.temp_dir.cleanup()

    def test_unknown_goal_returns_422_without_creating_path(self) -> None:
        with TestClient(create_app()) as client:
            demo = client.post("/api/v1/demo-data/load").json()["demo_data"]
            profile = client.get("/api/v1/student-profiles").json()[0]
            response = client.post("/api/v1/learning-paths", json={
                "student_profile_id": profile["id"], "course_id": demo["course_id"], "goal": "把这个再弄扎实一点"
            })
            self.assertEqual(response.status_code, 422)
            self.assertIn("知识点", response.json()["detail"])
        with session_scope(self.database_url) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(LearningPath)), 0)

    def test_path_persists_intent_targets_and_activity_fields(self) -> None:
        with TestClient(create_app()) as client:
            demo = client.post("/api/v1/demo-data/load").json()["demo_data"]
            profile = client.get("/api/v1/student-profiles").json()[0]
            response = client.post("/api/v1/learning-paths", json={
                "student_profile_id": profile["id"], "course_id": demo["course_id"],
                "goal": "巩固广搜和深搜，为课程小测做准备"
            })
            self.assertEqual(response.status_code, 200, response.text)
            path = response.json()["learning_path"]
            self.assertEqual(path["learning_intent"]["purpose"], "assessment_preparation")
            concept_by_id = {item["id"]: item["name"] for item in client.get(
                f"/api/v1/courses/{demo['course_id']}/graph"
            ).json()["concepts"]}
            self.assertEqual(
                {concept_by_id[item] for item in path["target_concept_ids"]},
                {"BFS/DFS"},
            )
            self.assertLessEqual(len(path["items"]), 8)
            self.assertEqual(len(path["milestones"]), 1)
            self.assertEqual(path["milestones"][0]["milestone_type"], "mock_assessment")
            target_minutes = sum(item["estimated_minutes"] for item in path["items"] if item["node_role"] == "target")
            prerequisite_minutes = sum(item["estimated_minutes"] for item in path["items"] if item["node_role"] == "prerequisite")
            self.assertGreater(target_minutes, prerequisite_minutes)
            for item in path["items"]:
                self.assertIn(item["node_role"], {"target", "prerequisite"})
                self.assertTrue(item["activity_type"])
                self.assertGreaterEqual(item["estimated_minutes"], 5)
                self.assertTrue(item["success_criterion"])

    def test_demo_reload_removes_obsolete_legacy_relations(self) -> None:
        demo = DemoDataService(database_url=self.database_url).load_demo_data().demo_data
        with session_scope(self.database_url) as session:
            concepts = {
                item.slug: item
                for item in session.scalars(select(Concept).where(Concept.course_id == demo.course_id)).all()
            }
            legacy_concept = Concept(
                course_id=demo.course_id,
                slug="legacy-stack-queue",
                name="旧版栈/队列",
                chapter="历史数据",
                description="旧版 Demo 概念，仅用于迁移测试。",
                difficulty="basic",
            )
            session.add(legacy_concept)
            session.flush()
            legacy_concept_id = legacy_concept.id
            traversal_id = concepts["binary-tree-traversal"].id
            session.add_all([
                ConceptRelation(
                    source_concept_id=concepts["complexity-analysis"].id,
                    target_concept_id=concepts["bfs-dfs"].id,
                    relation_type="prerequisite",
                ),
                ConceptRelation(
                    source_concept_id=concepts["binary-tree-traversal"].id,
                    target_concept_id=concepts["bfs-dfs"].id,
                    relation_type="prerequisite",
                ),
                ConceptRelation(
                    source_concept_id=legacy_concept_id,
                    target_concept_id=traversal_id,
                    relation_type="prerequisite",
                ),
            ])

        DemoDataService(database_url=self.database_url).load_demo_data()

        with session_scope(self.database_url) as session:
            concepts = {
                item.slug: item
                for item in session.scalars(select(Concept).where(Concept.course_id == demo.course_id)).all()
            }
            relations = session.scalars(select(ConceptRelation)).all()
            relation_keys = {
                (
                    next(slug for slug, concept in concepts.items() if concept.id == item.source_concept_id),
                    next(slug for slug, concept in concepts.items() if concept.id == item.target_concept_id),
                    item.relation_type,
                )
                for item in relations
                if item.source_concept_id in {concept.id for concept in concepts.values()}
                and item.target_concept_id in {concept.id for concept in concepts.values()}
            }
            self.assertNotIn(("complexity-analysis", "bfs-dfs", "prerequisite"), relation_keys)
            self.assertNotIn(("binary-tree-traversal", "bfs-dfs", "prerequisite"), relation_keys)
            self.assertIn(("graph-representation", "bfs-dfs", "prerequisite"), relation_keys)
            self.assertIsNone(session.scalar(select(ConceptRelation).where(
                ConceptRelation.source_concept_id == legacy_concept_id,
                ConceptRelation.target_concept_id == traversal_id,
            )))

    def test_quiz_goals_produce_exact_focus_and_minimal_paths(self) -> None:
        with TestClient(create_app()) as client:
            demo = client.post("/api/v1/demo-data/load").json()["demo_data"]
            profile = client.get("/api/v1/student-profiles").json()[0]
            concepts = client.get(f"/api/v1/courses/{demo['course_id']}/graph").json()["concepts"]
            names = {item["id"]: item["name"] for item in concepts}

            combined_response = client.post("/api/v1/learning-paths", json={
                "student_profile_id": profile["id"],
                "course_id": demo["course_id"],
                "goal": "巩固二叉树遍历和图搜索，为课程小测做准备",
            })
            self.assertEqual(combined_response.status_code, 200, combined_response.text)
            combined = combined_response.json()["learning_path"]
            self.assertEqual(
                {names[item] for item in combined["target_concept_ids"]},
                {"二叉树遍历", "BFS/DFS"},
            )
            self.assertEqual(
                {names[item["concept_id"]] for item in combined["items"]},
                {"树的基本概念", "二叉树", "二叉树遍历", "图的表示", "BFS/DFS"},
            )

            bfs_response = client.post("/api/v1/learning-paths", json={
                "student_profile_id": profile["id"],
                "course_id": demo["course_id"],
                "goal": "巩固深度搜索和广度搜索，为课程小测做准备",
            })
            self.assertEqual(bfs_response.status_code, 200, bfs_response.text)
            bfs_only = bfs_response.json()["learning_path"]
            self.assertEqual(
                {names[item] for item in bfs_only["target_concept_ids"]},
                {"BFS/DFS"},
            )
            self.assertEqual(
                {names[item["concept_id"]] for item in bfs_only["items"]},
                {"图的表示", "BFS/DFS"},
            )
            self.assertEqual(bfs_only["milestones"][0]["covered_concept_ids"], bfs_only["target_concept_ids"])


if __name__ == "__main__":
    unittest.main()
