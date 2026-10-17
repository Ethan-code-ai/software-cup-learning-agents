import json
import math
import os
import re
import unittest

from app.adapters.llm_provider import LLMSettings
from app.agents.planner_agents import PlannerConcept, PlannerContext, PlannerRelation, build_planner_agent
from app.agents.profile_builder_agents import build_profile_builder_agent
from app.agents.quiz_agents import QuizContext
from app.agents.quiz_factory import build_quiz_agent
from app.schemas import KnowledgeSearchResult, StudentProfileDialogueCreate


RUN_ONLINE = os.getenv("RUN_SPARK_ONLINE_TESTS", "").strip().lower() in {"1", "true", "yes", "on"}


def _percentile(values: list[int], quantile: float) -> int:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * quantile) - 1)]


@unittest.skipUnless(RUN_ONLINE, "set RUN_SPARK_ONLINE_TESTS=true to call the real Spark MaaS service")
class SparkNewAgentsPerformanceOnlineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = LLMSettings.from_env()

    def test_profile_builder_records_post_change_latency(self) -> None:
        self.assertTrue(
            self.settings.can_call_remote("profile_builder"),
            "Spark configuration is incomplete for profile_builder.",
        )
        self._report("profile_builder", self._profile_builder_samples(self.settings))

    def test_planner_records_post_change_latency(self) -> None:
        self.assertTrue(
            self.settings.can_call_remote("planner"),
            "Spark configuration is incomplete for planner.",
        )
        self._report("planner", self._planner_samples(self.settings))

    def test_quiz_records_post_change_latency(self) -> None:
        self.assertTrue(
            self.settings.can_call_remote("quiz"),
            "Spark configuration is incomplete for quiz.",
        )
        self._report("quiz", self._quiz_samples(self.settings))

    def _report(self, purpose: str, durations: list[int]) -> None:
        self.assertEqual(len(durations), 2)
        self.assertTrue(all(duration > 0 for duration in durations))
        print(
            "SPARK_PERF_EVIDENCE "
            + json.dumps(
                {
                    "purpose": purpose,
                    "sample_count": len(durations),
                    "provider_duration_ms_p50": _percentile(durations, 0.50),
                    "provider_duration_ms_p95": _percentile(durations, 0.95),
                    "fallback_count": 0,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            flush=True,
        )

    def _profile_builder_samples(self, settings: LLMSettings) -> list[int]:
        agent = build_profile_builder_agent(settings)
        dialogues = [
            "我基础一般，每天学习半小时，想用图解和例题掌握 BFS 与 DFS，容易混淆队列和栈。",
            "我有链表和树的基础，每周学习六小时，希望通过代码实操掌握图算法和复杂度分析。",
        ]
        durations: list[int] = []
        for dialogue in dialogues:
            result = agent.build(StudentProfileDialogueCreate(dialogue=dialogue))
            self.assertEqual(result.execution_mode, "llm", result.fallback_reason)
            self.assertFalse(result.fallback_used)
            durations.append(int(result.provider_metadata.get("provider_duration_ms") or 0))
        return durations

    def _planner_samples(self, settings: LLMSettings) -> list[int]:
        agent = build_planner_agent(settings)
        concepts = [
            PlannerConcept(1, "stack", "栈", "线性结构", "basic", "后进先出结构"),
            PlannerConcept(2, "queue", "队列", "线性结构", "basic", "先进先出结构"),
            PlannerConcept(3, "graph-representation", "图的表示", "图", "basic", "邻接表和邻接矩阵"),
            PlannerConcept(4, "bfs-dfs", "BFS/DFS", "图", "medium", "广度优先与深度优先搜索"),
            PlannerConcept(5, "shortest-path", "最短路径", "图", "medium", "无权图最短路径"),
        ]
        relations = [
            PlannerRelation(3, 4, "prerequisite"),
            PlannerRelation(4, 5, "prerequisite"),
            PlannerRelation(1, 4, "related"),
            PlannerRelation(2, 4, "related"),
        ]
        contexts = [
            PlannerContext(
                goal="巩固广搜和深搜，为课程小测做准备",
                profile_type="weak_foundation",
                foundation_level="beginner",
                learning_preference="step_by_step",
                available_time="一小时",
                weak_points=["队列和栈"],
                resource_preference="练习题",
            ),
            PlannerContext(
                goal="从零学习 BFS/DFS 并用 Python 实现",
                profile_type="algorithm_practice",
                foundation_level="intermediate",
                learning_preference="code_driven",
                available_time="两小时",
                weak_points=["访问标记"],
                resource_preference="代码实操案例",
            ),
        ]
        durations: list[int] = []
        for context in contexts:
            result = agent.plan(concepts, relations, context)
            self.assertEqual(result.execution_mode, "llm", result.fallback_reason)
            self.assertFalse(result.fallback_used)
            self.assertLessEqual(len(result.recommendations), 8)
            self.assertIn(4, result.target_concept_ids)
            durations.append(int(result.provider_metadata.get("provider_duration_ms") or 0))
        return durations

    def _quiz_samples(self, settings: LLMSettings) -> list[int]:
        agent = build_quiz_agent(settings)
        chunks = [
            KnowledgeSearchResult(
                chunk_id=9901,
                source_ref="document:99#chunk:1",
                score=0.99,
                content="广度优先搜索 BFS 使用队列按层访问；深度优先搜索 DFS 使用递归栈或显式栈深入后回溯。",
            )
        ]
        contexts = [
            QuizContext(
                profile_preferences={"profile_type": "exam_sprint", "learning_preference": "worked_examples"},
                mastery_score=0.45,
                recent_errors=["混淆队列和栈"],
            ),
            QuizContext(
                profile_preferences={"profile_type": "algorithm_practice", "learning_preference": "code_driven"},
                mastery_score=0.72,
                recent_errors=["遗漏访问标记"],
            ),
        ]
        durations: list[int] = []
        for context in contexts:
            result = agent.generate("BFS 与 DFS", "medium", chunks, context)
            self.assertEqual(result.execution_mode, "llm", result.fallback_reason)
            self.assertFalse(result.fallback_used)
            self.assertTrue(result.source_refs)
            self.assertRegex(result.question, r"[\u4e00-\u9fff]")
            self.assertRegex(result.explanation, r"[\u4e00-\u9fff]")
            if result.question_type == "multiple_choice":
                self.assertTrue(result.options)
                self.assertTrue(all(re.search(r"[\u4e00-\u9fff]", option) for option in result.options))
            durations.append(int(result.provider_metadata.get("provider_duration_ms") or 0))
        return durations


if __name__ == "__main__":
    unittest.main()
