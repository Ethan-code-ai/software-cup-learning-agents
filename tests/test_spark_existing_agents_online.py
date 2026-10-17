import hashlib
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from sqlalchemy import select

from app.adapters.llm_provider import LLMSettings
from app.agents.critic_agents import RuleBasedCriticAgent
from app.agents.evaluator_factory import build_evaluator_agent
from app.agents.resource_factory import build_resource_agent
from app.agents.tutor_factory import build_tutor_agent
from app.db.session import get_engine, session_scope
from app.models import AgentRun, AgentRunStep, StudentProfileHistory
from app.schemas import KnowledgeSearchResult
from app.services.citation_service import validate_citations
from app.services.agent_run_service import AgentRunService
from app.services.demo_data_service import DemoDataService
from app.services.profile_service import ProfileService
from app.services.profile_updater_service import ProfileUpdaterService
from app.services.tutor_service import TutorService


RUN_ONLINE = os.getenv("RUN_SPARK_ONLINE_TESTS", "").strip().lower() in {"1", "true", "yes", "on"}


@unittest.skipUnless(RUN_ONLINE, "set RUN_SPARK_ONLINE_TESTS=true to call the real Spark MaaS service")
class SparkExistingAgentsOnlineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = LLMSettings.from_env()
        for purpose in ("tutor", "resource", "evaluator", "profile_updater"):
            if not cls.settings.can_call_remote(purpose):
                raise AssertionError(f"Spark configuration is incomplete for {purpose}.")
        cls.chunks = [
            KnowledgeSearchResult(
                chunk_id=901,
                source_ref="document:90#chunk:1",
                score=0.98,
                content=(
                    "广度优先搜索 BFS 使用队列，按层访问图中顶点；"
                    "在邻接表表示下时间复杂度为 O(V+E)。"
                ),
            ),
            KnowledgeSearchResult(
                chunk_id=902,
                source_ref="document:90#chunk:2",
                score=0.96,
                content=(
                    "深度优先搜索 DFS 使用递归或显式栈，沿分支深入后回溯；"
                    "在邻接表表示下时间复杂度为 O(V+E)。"
                ),
            ),
        ]

    def test_resource_five_types_are_real_llm_distinct_grounded_and_critic_approved(self) -> None:
        agent = build_resource_agent(self.settings)
        critic = RuleBasedCriticAgent()
        profile = {
            "foundation_level": "intermediate",
            "learning_preference": "code_driven",
            "resource_preference": "代码实操案例",
        }
        markers = {
            "guided_note": ("核心", "易错"),
            "practice_questions": ("题目", "解析"),
            "mind_map": ("中心主题", "分支"),
            "extended_reading": ("阅读目标", "延伸"),
            "coding_case": ("```python", "复杂度"),
        }
        digests: list[str] = []

        for resource_type, required_markers in markers.items():
            with self.subTest(resource_type=resource_type):
                started = time.perf_counter()
                result = agent.generate(
                    "BFS 与 DFS",
                    "区分遍历策略、数据结构、复杂度和适用场景",
                    resource_type,
                    self.chunks,
                    profile,
                )
                review = critic.review_resource(result, resource_type, profile)
                digest = hashlib.sha256(result.content.encode("utf-8")).hexdigest()[:12]
                digests.append(digest)

                self.assertNotIn("Fallback reason:", result.decision_basis)
                self.assertTrue(review.approved, review.output_summary)
                self.assertEqual(len(result.source_refs), 2)
                for marker in required_markers:
                    self.assertIn(marker, result.content)
                self._print_evidence(
                    capability=f"resource:{resource_type}",
                    execution_mode="llm",
                    critic_approved=True,
                    content_length=len(result.content),
                    content_sha256=digest,
                    source_ref_count=len(result.source_refs),
                    duration_ms=self._duration_ms(started),
                )

        self.assertEqual(len(set(digests)), len(markers))

    def test_resource_same_type_changes_for_distinct_profiles(self) -> None:
        agent = build_resource_agent(self.settings)
        profiles = {
            "beginner_visual": {
                "foundation_level": "beginner",
                "learning_preference": "visual_map",
                "available_time": "15 minutes",
            },
            "intermediate_code": {
                "foundation_level": "intermediate",
                "learning_preference": "code_driven",
                "available_time": "45 minutes",
            },
        }
        digests: dict[str, str] = {}
        for profile_name, profile in profiles.items():
            started = time.perf_counter()
            result = agent.generate(
                "BFS 与 DFS",
                "区分遍历策略、数据结构、复杂度和适用场景",
                "guided_note",
                self.chunks,
                profile,
            )
            self.assertNotIn("Fallback reason:", result.decision_basis)
            digest = hashlib.sha256(result.content.encode("utf-8")).hexdigest()[:12]
            digests[profile_name] = digest
            self._print_evidence(
                capability=f"resource_profile:{profile_name}",
                execution_mode="llm",
                content_length=len(result.content),
                content_sha256=digest,
                duration_ms=self._duration_ms(started),
            )
        self.assertEqual(len(set(digests.values())), 2)

    def test_tutor_is_real_llm_and_citations_are_whitelisted(self) -> None:
        started = time.perf_counter()
        result = build_tutor_agent(self.settings).answer(
            "我应该如何区分广度优先搜索和深度优先搜索？",
            self.chunks,
            "中等基础，偏好代码示例",
            "数据结构",
        )
        citation_check = validate_citations(result.answer, result.source_refs)

        self.assertNotIn("Fallback reason:", result.decision_basis)
        self.assertFalse(citation_check["missing_citation"])
        self.assertEqual(citation_check["fake_source_refs"], [])
        self.assertGreaterEqual(len(citation_check["cited_source_refs"]), 1)
        self.assertLessEqual(len(result.answer), 450)
        self.assertRegex(result.answer, r"[\u4e00-\u9fff]")
        self._print_evidence(
            capability="tutor",
            execution_mode="llm",
            answer_length=len(result.answer),
            allowed_source_ref_count=len(citation_check["allowed_source_refs"]),
            cited_source_ref_count=len(citation_check["cited_source_refs"]),
            duration_ms=self._duration_ms(started),
        )

    def test_tutor_without_retrieval_returns_limitation_without_remote_generation(self) -> None:
        result = build_tutor_agent(self.settings).answer("请解释课程资料中没有覆盖的算法。", [])

        self.assertIn("暂未检索到足够资料", result.answer)
        self.assertEqual(result.source_refs, [])
        self.assertIn("No retrieved course chunks", result.decision_basis)
        self._print_evidence(
            capability="tutor:no_retrieval",
            execution_mode="rule_based_fallback",
            fallback_reason="no_retrieved_course_chunks",
        )

    def test_real_tutor_service_persists_safe_structured_execution_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_url = f"sqlite:///{(Path(temp_dir) / 'comp007-online.sqlite3').as_posix()}"
            demo = DemoDataService(database_url=database_url).load_demo_data().demo_data
            profile = ProfileService(database_url=database_url).list_demo_profiles()[0]
            tutor_service = TutorService(database_url=database_url)
            previous_updater_flag = os.environ.get("LLM_ENABLE_FOR_PROFILE_UPDATER")
            os.environ["LLM_ENABLE_FOR_PROFILE_UPDATER"] = "false"
            try:
                answer = tutor_service.ask(
                    profile.id,
                    demo.course_id,
                    "BFS 为什么使用队列，并且在邻接表下复杂度是多少？",
                )
            finally:
                if previous_updater_flag is None:
                    os.environ.pop("LLM_ENABLE_FOR_PROFILE_UPDATER", None)
                else:
                    os.environ["LLM_ENABLE_FOR_PROFILE_UPDATER"] = previous_updater_flag

            run = AgentRunService(database_url=database_url).get_run(answer.agent_run_id)
            tutor_step = next(step for step in run.steps if str(step.agent_type) == "tutor")
            metadata = tutor_step.execution_metadata
            serialized = json.dumps(run.model_dump(mode="json"), ensure_ascii=False)

            self.assertEqual(metadata.execution_mode, "llm")
            self.assertEqual(metadata.provider, self.settings.provider)
            self.assertEqual(metadata.model, self.settings.model)
            self.assertFalse(metadata.fallback_used)
            self.assertTrue(metadata.source_refs)
            self.assertNotIn(self.settings.api_key, serialized)
            print(
                "COMP007_EVIDENCE "
                + json.dumps(
                    {
                        "capability": "agent_trace:tutor",
                        "execution_mode": metadata.execution_mode,
                        "provider": metadata.provider,
                        "model": metadata.model,
                        "source_ref_count": len(metadata.source_refs),
                        "duration_ms": metadata.duration_ms,
                        "secret_absent": True,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                flush=True,
            )
            get_engine(database_url).dispose()

    def test_evaluator_returns_real_llm_structured_assessment(self) -> None:
        started = time.perf_counter()
        result = build_evaluator_agent(self.settings).evaluate(
            (
                "BFS 使用队列按层遍历，DFS 使用递归栈或显式栈深入后回溯；"
                "邻接表下二者复杂度均为 O(V+E)。"
            ),
            {"answer": "BFS 用队列按层，DFS 用栈深入，二者邻接表复杂度都是 O(V+E)。"},
            901,
        )

        self.assertNotIn("Fallback reason:", result.decision_basis)
        self.assertGreaterEqual(result.score, 0.0)
        self.assertLessEqual(result.score, 1.0)
        self.assertTrue(result.feedback.strip())
        self.assertEqual(len(result.mastery_updates), 1)
        self.assertEqual(result.mastery_updates[0]["evidence"]["analysis_method"], "llm")
        self._print_evidence(
            capability="evaluator",
            execution_mode="llm",
            score=result.score,
            feedback_length=len(result.feedback),
            mastery_update_count=len(result.mastery_updates),
            duration_ms=self._duration_ms(started),
        )

    def test_profile_updater_uses_real_trace_and_no_evidence_is_a_noop(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_url = f"sqlite:///{(Path(temp_dir) / 'comp006-online.sqlite3').as_posix()}"
            demo = DemoDataService(database_url=database_url).load_demo_data().demo_data
            profiles = ProfileService(database_url=database_url).list_demo_profiles()
            active_profile_id = profiles[0].id
            clean_profile_id = profiles[1].id
            with session_scope(database_url) as session:
                run = AgentRun(
                    student_profile_id=active_profile_id,
                    course_id=demo.course_id,
                    run_type="comp006_online_acceptance",
                    status="completed",
                    input_summary="Controlled COMP-006 learning trace.",
                    output_summary="Controlled COMP-006 learning trace.",
                    final_summary="Controlled COMP-006 learning trace.",
                )
                session.add(run)
                session.flush()
                session.add(
                    AgentRunStep(
                        agent_run_id=run.id,
                        agent_type="evaluator",
                        step_order=1,
                        status="completed",
                        input_summary="学生提交了 BFS 与 DFS 对比回答。",
                        output_summary="评分 0.55；薄弱点为遍历所用数据结构和适用场景。",
                        decision_basis="证据来自本次学生作答与标准答案比较。",
                    )
                )

            started = time.perf_counter()
            updater = ProfileUpdaterService(database_url=database_url)
            updater.update_from_trace(
                active_profile_id,
                trigger_type="comp006_online",
                event_key="comp006_online:real_trace",
            )
            with session_scope(database_url) as session:
                history = session.scalar(
                    select(StudentProfileHistory).where(
                        StudentProfileHistory.event_key == "comp006_online:real_trace"
                    )
                )
                profile_run = session.scalar(
                    select(AgentRun)
                    .where(
                        AgentRun.student_profile_id == active_profile_id,
                        AgentRun.run_type == "profile_update",
                    )
                    .order_by(AgentRun.id.desc())
                )
                profile_step = (
                    session.scalar(
                        select(AgentRunStep).where(
                            AgentRunStep.agent_run_id == profile_run.id,
                            AgentRunStep.agent_type == "profile_updater",
                        )
                    )
                    if profile_run is not None
                    else None
                )

            self.assertIsNotNone(history)
            self.assertTrue(history.changed_dimensions)
            self.assertGreaterEqual(len(history.evidence_refs), 2)
            self.assertIsNotNone(profile_step)
            self.assertIn("method=llm", profile_step.input_summary)
            self._print_evidence(
                capability="profile_updater",
                execution_mode="llm",
                changed_dimension_count=len(history.changed_dimensions),
                evidence_ref_count=len(history.evidence_refs),
                duration_ms=self._duration_ms(started),
            )

            before = ProfileService(database_url=database_url).get_profile(clean_profile_id)
            history_before = updater.list_history(clean_profile_id)
            after = updater.update_from_trace(clean_profile_id)
            history_after = updater.list_history(clean_profile_id)
            self.assertEqual(before.model_dump(), after.model_dump())
            self.assertEqual(history_before, history_after)
            self._print_evidence(
                capability="profile_updater:no_evidence",
                execution_mode="no_op",
                profile_unchanged=True,
                history_unchanged=True,
            )
            get_engine(database_url).dispose()

    @staticmethod
    def _duration_ms(started: float) -> int:
        return round((time.perf_counter() - started) * 1000)

    @staticmethod
    def _print_evidence(**payload: object) -> None:
        print(f"COMP006_EVIDENCE {json.dumps(payload, ensure_ascii=False, sort_keys=True)}", flush=True)


if __name__ == "__main__":
    unittest.main()
