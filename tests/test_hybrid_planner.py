import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.adapters.llm_provider import LLMSettings
from app.adapters.protocols import LLMResult
from app.agents.planner_agents import (
    HybridPlannerAgent,
    PlannerConcept,
    PlannerContext,
    PlannerRelation,
    RuleBasedHybridPlannerAgent,
    build_planner_agent,
)
from app.db.session import get_engine
from app.main import create_app


class SequentialPlannerProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def generate(self, messages, response_schema=None) -> LLMResult:
        self.calls.append((messages, response_schema))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return LLMResult(content=json.dumps(response, ensure_ascii=False), metadata={"provider": "fake", "model": "planner-test"})


def _resolution():
    return {
        "course_scope": "focused",
        "target_concept_ids": [20],
        "optional_support_concept_ids": [],
        "purpose": "project_application",
        "action": "practice",
        "assessment_type": "none",
        "time_horizon": "short_term",
        "preferred_activities": ["coding"],
        "desired_outcome": "能够实现并解释实践节点",
        "confidence": 0.91,
    }


def _activities():
    return {"activities": [
        {"concept_id": 20, "node_role": "target", "activity_type": "coding", "objective": "完成代码实现", "estimated_minutes": 30, "success_criterion": "代码通过样例并能解释复杂度", "recommended_resource_type": "coding_case", "reason": "匹配代码实践目标", "priority": 1}
    ]}


class HybridPlannerAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.concepts = [
            PlannerConcept(30, "foundation", "基础", "第一章", "basic"),
            PlannerConcept(10, "advanced", "进阶", "第二章", "medium"),
            PlannerConcept(20, "practice", "实践", "第三章", "basic"),
        ]
        self.relations = [PlannerRelation(30, 10)]

    def test_rule_based_full_course_uses_topology(self) -> None:
        result = RuleBasedHybridPlannerAgent().plan(self.concepts, self.relations, self._context("系统掌握整门课程"))
        order = [item.concept_id for item in result.recommendations]
        self.assertLess(order.index(30), order.index(10))
        self.assertEqual(result.execution_mode, "rule_based")

    def test_two_llm_phases_return_valid_activity_without_expanding_nodes(self) -> None:
        provider = SequentialPlannerProvider([_resolution(), _activities()])
        result = HybridPlannerAgent(provider, provider_name="fake", model="planner-test").plan(
            self.concepts, self.relations, self._context("使用代码实践")
        )
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual([item.concept_id for item in result.recommendations], [20])
        self.assertEqual(result.recommendations[0].activity_type, "coding")
        self.assertEqual(result.execution_mode, "llm")
        self.assertEqual([item.phase for item in result.phase_traces], ["goal_resolution", "constraint_validation", "activity_generation"])

    def test_activity_timeout_keeps_resolved_node_set_and_falls_back(self) -> None:
        provider = SequentialPlannerProvider([_resolution(), TimeoutError("activity timeout")])
        result = HybridPlannerAgent(provider).plan(self.concepts, self.relations, self._context("使用代码实践"))
        self.assertEqual([item.concept_id for item in result.recommendations], [20])
        self.assertEqual(result.execution_mode, "rule_based_fallback")
        self.assertIn("activity_generation", result.fallback_reason or "")

    def test_explicit_bfs_goal_repairs_llm_extra_target(self) -> None:
        concepts = [
            PlannerConcept(4, "bfs-dfs", "BFS/DFS", "图", "medium"),
            PlannerConcept(6, "asymptotic-notation", "渐进记号", "复杂度", "basic"),
        ]
        resolution = {
            "course_scope": "focused",
            "target_concept_ids": [4, 6],
            "optional_support_concept_ids": [],
            "purpose": "assessment_preparation",
            "action": "consolidate",
            "assessment_type": "course_quiz",
            "time_horizon": "short_term",
            "preferred_activities": ["concept_comparison", "mock_assessment"],
            "desired_outcome": "能够区分两种算法",
            "confidence": 0.9,
        }
        activities = {"activities": [{
            "concept_id": 4,
            "node_role": "target",
            "activity_type": "error_review",
            "objective": "对比 BFS 与 DFS 并复盘易错点",
            "estimated_minutes": 35,
            "success_criterion": "完成典型题并解释队列、栈和访问顺序",
            "recommended_resource_type": "practice_questions",
            "reason": "匹配课程小测目标",
            "priority": 1,
        }]}
        result = HybridPlannerAgent(SequentialPlannerProvider([resolution, activities])).plan(
            concepts,
            [],
            PlannerContext(
                goal="巩固深度搜索和广度搜索，为课程小测做准备",
                profile_type="exam_sprint",
                foundation_level="beginner",
                learning_preference="step_by_step",
                available_time="一小时",
                weak_points=[],
                resource_preference="练习题",
            ),
        )

        self.assertEqual(result.target_concept_ids, [4])
        self.assertEqual([item.concept_id for item in result.recommendations], [4])
        self.assertEqual(result.execution_mode, "llm")
        self.assertIn("target_anchors_repaired", result.warning_reason or "")
        self.assertEqual(result.phase_traces[0].warning_reason, "target_anchors_repaired")

    def test_quiz_fallback_prioritizes_targets_and_adds_path_assessment(self) -> None:
        concepts = [
            PlannerConcept(3, "graph-representation", "图的表示", "图", "basic"),
            PlannerConcept(4, "bfs-dfs", "BFS/DFS", "图", "medium", "广度优先与深度优先搜索"),
        ]
        resolution = {
            "course_scope": "focused",
            "target_concept_ids": [4],
            "optional_support_concept_ids": [],
            "purpose": "assessment_preparation",
            "action": "consolidate",
            "assessment_type": "course_quiz",
            "time_horizon": "short_term",
            "preferred_activities": ["concept_comparison", "mock_assessment"],
            "desired_outcome": "能够区分 BFS 与 DFS",
            "confidence": 0.9,
        }
        result = HybridPlannerAgent(
            SequentialPlannerProvider([resolution, TimeoutError("activity timeout")])
        ).plan(
            concepts,
            [PlannerRelation(3, 4, "prerequisite")],
            PlannerContext(
                goal="巩固 BFS/DFS，为课程小测做准备",
                profile_type="exam_sprint",
                foundation_level="beginner",
                learning_preference="step_by_step",
                available_time="一小时",
                weak_points=["BFS/DFS"],
                resource_preference="练习题",
            ),
        )

        prerequisite, target = result.recommendations
        self.assertEqual(prerequisite.activity_type, "worked_example")
        self.assertNotEqual(prerequisite.activity_type, "mock_assessment")
        self.assertGreater(target.estimated_minutes, prerequisite.estimated_minutes)
        self.assertIn("易错点", target.objective)
        self.assertEqual(len(result.milestones), 1)
        self.assertEqual(result.milestones[0].milestone_type, "mock_assessment")
        self.assertEqual(result.milestones[0].covered_concept_ids, [4])

    def test_quiz_llm_output_without_target_focus_is_rejected(self) -> None:
        concepts = [
            PlannerConcept(3, "graph-representation", "图的表示", "图", "basic"),
            PlannerConcept(4, "bfs-dfs", "BFS/DFS", "图", "medium"),
        ]
        resolution = {
            "course_scope": "focused",
            "target_concept_ids": [4],
            "optional_support_concept_ids": [],
            "purpose": "assessment_preparation",
            "action": "consolidate",
            "assessment_type": "course_quiz",
            "time_horizon": "short_term",
            "preferred_activities": ["concept_comparison", "mock_assessment"],
            "desired_outcome": "完成小测准备",
            "confidence": 0.9,
        }
        unfocused = {"activities": [
            {
                "concept_id": 3,
                "node_role": "prerequisite",
                "activity_type": "mock_assessment",
                "objective": "测试图的表示",
                "estimated_minutes": 20,
                "success_criterion": "完成练习",
                "recommended_resource_type": "practice_questions",
                "reason": "准备小测",
                "priority": 1,
            },
            {
                "concept_id": 4,
                "node_role": "target",
                "activity_type": "concept_comparison",
                "objective": "对比 BFS 与 DFS",
                "estimated_minutes": 20,
                "success_criterion": "完成练习",
                "recommended_resource_type": "practice_questions",
                "reason": "准备小测",
                "priority": 2,
            },
        ]}
        result = HybridPlannerAgent(SequentialPlannerProvider([resolution, unfocused])).plan(
            concepts,
            [PlannerRelation(3, 4, "prerequisite")],
            PlannerContext(
                goal="巩固 BFS/DFS，为课程小测做准备",
                profile_type="exam_sprint",
                foundation_level="beginner",
                learning_preference="step_by_step",
                available_time="一小时",
                weak_points=[],
                resource_preference="练习题",
            ),
        )

        self.assertEqual(result.execution_mode, "rule_based_fallback")
        prerequisite, target = result.recommendations
        self.assertEqual(prerequisite.activity_type, "worked_example")
        self.assertGreater(target.estimated_minutes, prerequisite.estimated_minutes)

    def test_resource_type_in_activity_field_is_safely_repaired(self) -> None:
        concepts = [PlannerConcept(4, "bfs-dfs", "BFS/DFS", "图", "medium")]
        resolution = {
            "course_scope": "focused",
            "target_concept_ids": [4],
            "optional_support_concept_ids": [],
            "purpose": "assessment_preparation",
            "action": "consolidate",
            "assessment_type": "course_quiz",
            "time_horizon": "short_term",
            "preferred_activities": ["concept_comparison", "mock_assessment"],
            "desired_outcome": "完成小测准备",
            "confidence": 0.9,
        }
        confused_activity = {"activities": [{
            "concept_id": 4,
            "node_role": "target",
            "activity_type": "guided_note",
            "objective": "对比 BFS 与 DFS",
            "estimated_minutes": 35,
            "success_criterion": "完成两道典型题",
            "recommended_resource_type": "guided_note",
            "reason": "匹配小测目标",
            "priority": 1,
        }]}
        result = HybridPlannerAgent(
            SequentialPlannerProvider([resolution, confused_activity])
        ).plan(
            concepts,
            [],
            PlannerContext(
                goal="巩固 BFS/DFS，为课程小测做准备",
                profile_type="exam_sprint",
                foundation_level="beginner",
                learning_preference="step_by_step",
                available_time="一小时",
                weak_points=[],
                resource_preference="练习题",
            ),
        )

        self.assertEqual(result.execution_mode, "llm")
        self.assertEqual(result.recommendations[0].activity_type, "explanation")
        self.assertIn("activity_type_repaired", result.warning_reason or "")

    def test_quiz_llm_time_is_rebalanced_without_discarding_content(self) -> None:
        concepts = [
            PlannerConcept(3, "graph-representation", "图的表示", "图", "basic"),
            PlannerConcept(4, "bfs-dfs", "BFS/DFS", "图", "medium"),
        ]
        resolution = {
            "course_scope": "focused",
            "target_concept_ids": [4],
            "optional_support_concept_ids": [],
            "purpose": "assessment_preparation",
            "action": "consolidate",
            "assessment_type": "course_quiz",
            "time_horizon": "short_term",
            "preferred_activities": ["worked_example", "error_review"],
            "desired_outcome": "完成小测准备",
            "confidence": 0.9,
        }
        activities = {"activities": [
            {
                "concept_id": 3,
                "node_role": "prerequisite",
                "activity_type": "worked_example",
                "objective": "确认图表示基础",
                "estimated_minutes": 20,
                "success_criterion": "完成诊断题",
                "recommended_resource_type": "practice_questions",
                "reason": "检查先修",
                "priority": 1,
            },
            {
                "concept_id": 4,
                "node_role": "target",
                "activity_type": "error_review",
                "objective": "保留这段 LLM 生成的重点复盘内容",
                "estimated_minutes": 20,
                "success_criterion": "完成两道典型题",
                "recommended_resource_type": "practice_questions",
                "reason": "匹配小测",
                "priority": 2,
            },
        ]}
        result = HybridPlannerAgent(SequentialPlannerProvider([resolution, activities])).plan(
            concepts,
            [PlannerRelation(3, 4, "prerequisite")],
            PlannerContext(
                goal="巩固 BFS/DFS，为课程小测做准备",
                profile_type="exam_sprint",
                foundation_level="beginner",
                learning_preference="step_by_step",
                available_time="一小时",
                weak_points=[],
                resource_preference="练习题",
            ),
        )

        prerequisite, target = result.recommendations
        self.assertEqual(result.execution_mode, "llm")
        self.assertEqual(prerequisite.estimated_minutes, 5)
        self.assertEqual(target.estimated_minutes, 40)
        self.assertIn("保留这段 LLM", target.objective)
        self.assertIn("assessment_time_rebalanced", result.warning_reason or "")

    def test_activity_with_wrong_node_role_is_rejected_and_falls_back(self) -> None:
        invalid = _activities()
        invalid["activities"][0]["node_role"] = "prerequisite"
        result = HybridPlannerAgent(SequentialPlannerProvider([_resolution(), invalid])).plan(
            self.concepts, self.relations, self._context("使用代码实践")
        )
        self.assertEqual(result.execution_mode, "rule_based_fallback")
        self.assertEqual(result.recommendations[0].node_role, "target")

    def test_rule_fallback_distributes_chinese_time_budget(self) -> None:
        result = RuleBasedHybridPlannerAgent().plan(
            self.concepts, self.relations, self._context("系统掌握整门课程")
        )
        self.assertLessEqual(sum(item.estimated_minutes for item in result.recommendations), 60)

    def test_factory_uses_planner_specific_flag(self) -> None:
        settings = LLMSettings(provider="openai_compatible", base_url="https://example.invalid/v1", api_key="test", model="test", enable_for_planner=True)
        self.assertIsInstance(build_planner_agent(settings), HybridPlannerAgent)
        with patch.dict(os.environ, {"LLM_PROVIDER": "openai_compatible", "LLM_BASE_URL": "https://example.invalid/v1", "LLM_API_KEY": "test", "LLM_MODEL": "test", "LLM_ENABLE_FOR_PLANNER": "true"}, clear=True):
            self.assertTrue(LLMSettings.from_env().enable_for_planner)

    @staticmethod
    def _context(goal: str) -> PlannerContext:
        return PlannerContext(goal=goal, profile_type="practice", foundation_level="intermediate", learning_preference="code_driven", available_time="每天一小时", weak_points=[], resource_preference="代码实操案例")


class HybridPlannerApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "hybrid-planner.sqlite3"
        self.database_url = f"sqlite:///{database_path.as_posix()}"
        os.environ["APP_DATABASE_URL"] = self.database_url

    def tearDown(self) -> None:
        get_engine().dispose(); get_engine(self.database_url).dispose(); get_engine.cache_clear()
        os.environ.pop("APP_DATABASE_URL", None); self.temp_dir.cleanup()

    def test_focused_api_path_is_small_and_respects_hard_prerequisites(self) -> None:
        with TestClient(create_app()) as client:
            demo = client.post("/api/v1/demo-data/load").json()["demo_data"]
            profile = client.get("/api/v1/student-profiles").json()[0]
            graph = client.get(f"/api/v1/courses/{demo['course_id']}/graph").json()
            response = client.post("/api/v1/learning-paths", json={"student_profile_id": profile["id"], "course_id": demo["course_id"], "goal": "巩固 BFS/DFS，为课程小测做准备"})
            self.assertEqual(response.status_code, 200, response.text)
            flow = response.json(); path = flow["learning_path"]
            self.assertLessEqual(len(path["items"]), 8)
            positions = {item["concept_id"]: item["order_index"] for item in path["items"]}
            for relation in graph["relations"]:
                if relation["relation_type"] == "prerequisite" and relation["source_concept_id"] in positions and relation["target_concept_id"] in positions:
                    self.assertLess(positions[relation["source_concept_id"]], positions[relation["target_concept_id"]])
            planner_steps = [step for step in flow["agent_run"]["steps"] if step["agent_type"] == "planner"]
            self.assertEqual(len(planner_steps), 3)


if __name__ == "__main__":
    unittest.main()
