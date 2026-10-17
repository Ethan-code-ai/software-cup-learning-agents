import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.base import Base
from app.db.session import get_engine, get_session_factory
from app.main import create_app
from app.models import Concept, Course, Document, LearningPath, LearningPathItem, StudentProfile
from app.services.knowledge_base_service import KnowledgeBaseService
from app.seed.demo_data import DEMO_CHAPTERS, DEMO_CONCEPTS


class RagRetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "rag-retrieval.sqlite3"
        self.database_url = f"sqlite:///{self.database_path.as_posix()}"
        os.environ["APP_DATABASE_URL"] = self.database_url
        Base.metadata.create_all(get_engine(self.database_url))
        self.course_id, self.profile_id, self.path_item_id = self._seed_minimum_learning_records()

    def tearDown(self) -> None:
        get_engine().dispose()
        get_engine(self.database_url).dispose()
        get_engine.cache_clear()
        os.environ.pop("APP_DATABASE_URL", None)
        self.temp_dir.cleanup()

    def test_knowledge_search_hits_imported_document_without_demo_seed(self) -> None:
        with TestClient(create_app()) as client:
            document = self._ingest_bfs_document(client)
            search = client.post(
                "/api/v1/knowledge/search",
                json={"course_id": self.course_id, "query": "BFS 最短路径 queue", "top_k": 3},
            )
            self.assertEqual(search.status_code, 200)
            results = search.json()["results"]
            self.assertTrue(results)
            self.assertEqual(results[0]["source_ref"], f"document:{document['id']}#chunk:0")
            self.assertEqual(results[0]["metadata"]["retrieval_mode"], "keyword")
            self.assertGreater(results[0]["metadata"]["term_match_count"], 0)
            self.assertTrue(results[0]["metadata"]["matched_terms"])

            session = get_session_factory(self.database_url)()
            try:
                demo_documents = session.scalars(select(Document).where(Document.source_type == "demo")).all()
                self.assertEqual(demo_documents, [])
            finally:
                session.close()

    def test_demo_course_loads_a_searchable_document_for_every_chapter(self) -> None:
        with TestClient(create_app()) as client:
            loaded = client.post("/api/v1/demo-data/load")
            self.assertEqual(loaded.status_code, 200)
            course_id = loaded.json()["demo_data"]["course_id"]

            graph = client.get(f"/api/v1/courses/{course_id}/graph").json()
            self.assertEqual(len(graph["concepts"]), len(DEMO_CONCEPTS))
            self.assertEqual({concept["chapter"] for concept in graph["concepts"]}, {
                chapter["chapter"] for chapter in DEMO_CHAPTERS
            })
            self.assertGreaterEqual(len(graph["relations"]), len(DEMO_CONCEPTS) - len(DEMO_CHAPTERS))

            for chapter in DEMO_CHAPTERS:
                response = client.post(
                    "/api/v1/knowledge/search",
                    json={
                        "course_id": course_id,
                        "query": chapter["search_query"],
                        "top_k": 3,
                    },
                )
                self.assertEqual(response.status_code, 200)
                results = response.json()["results"]
                self.assertTrue(results, chapter["chapter"])
                self.assertTrue(
                    any(result["source_ref"].startswith("document:") for result in results),
                    chapter["chapter"],
                )

    def test_auto_loaded_course_sources_ground_tutor_and_resource(self) -> None:
        with TestClient(create_app()) as client:
            loaded = client.post("/api/v1/demo-data/load").json()["demo_data"]
            course_id = loaded["course_id"]
            profile_id = client.get("/api/v1/student-profiles").json()[0]["id"]
            path = client.post(
                "/api/v1/learning-paths",
                json={
                    "student_profile_id": profile_id,
                    "course_id": course_id,
                    "goal": "掌握二分查找和排序基础",
                },
            ).json()["learning_path"]

            tutor = client.post(
                "/api/v1/tutor/ask",
                json={
                    "student_profile_id": profile_id,
                    "course_id": course_id,
                    "question": "二分查找为什么需要有序序列？它的时间复杂度是什么？",
                },
            ).json()
            self.assertTrue(tutor["source_refs"])
            self.assertTrue(any(ref["source_ref"].startswith("document:") for ref in tutor["source_refs"]))

            resource = client.post(
                "/api/v1/resources/generate",
                json={"path_item_id": path["items"][0]["id"], "resource_type": "guided_note"},
            ).json()
            self.assertTrue(resource["source_refs"])
            self.assertTrue(any(ref["source_ref"].startswith("document:") for ref in resource["source_refs"]))

    def test_tutor_and_resource_preserve_real_document_source_refs(self) -> None:
        with TestClient(create_app()) as client:
            document = self._ingest_bfs_document(client)
            expected_source_ref = f"document:{document['id']}#chunk:0"

            tutor = client.post(
                "/api/v1/tutor/ask",
                json={
                    "student_profile_id": self.profile_id,
                    "course_id": self.course_id,
                    "question": "BFS 为什么适合无权图最短路径？",
                },
            )
            self.assertEqual(tutor.status_code, 200)
            tutor_body = tutor.json()
            self.assertTrue(tutor_body["answer"])
            self.assertEqual(tutor_body["source_refs"][0]["source_ref"], expected_source_ref)
            tutor_run = client.get(f"/api/v1/agent-runs/{tutor_body['agent_run_id']}").json()
            tutor_step = next(step for step in tutor_run["steps"] if step["agent_type"] == "tutor")
            self.assertIn(expected_source_ref, tutor_step["output_summary"])
            self.assertIn(expected_source_ref, tutor_step["decision_basis"])
            self.assertEqual(tutor_step["execution_metadata"]["execution_mode"], "rule_based")
            self.assertEqual(tutor_step["execution_metadata"]["source_refs"], [expected_source_ref])

            resource = client.post(
                "/api/v1/resources/generate",
                json={"path_item_id": self.path_item_id, "resource_type": "guided_note"},
            )
            self.assertEqual(resource.status_code, 200)
            resource_body = resource.json()
            self.assertTrue(resource_body["content"])
            self.assertEqual(resource_body["source_refs"][0]["source_ref"], expected_source_ref)
            resource_run = client.get(f"/api/v1/agent-runs/{resource_body['agent_run_id']}").json()
            resource_step = next(step for step in resource_run["steps"] if step["agent_type"] == "resource")
            self.assertIn(expected_source_ref, resource_step["output_summary"])
            self.assertIn(expected_source_ref, resource_step["decision_basis"])
            self.assertEqual(resource_step["execution_metadata"]["execution_mode"], "rule_based")
            self.assertEqual(resource_step["execution_metadata"]["source_refs"], [expected_source_ref])

    def test_search_returns_empty_results_without_matching_chunks_or_demo_seed(self) -> None:
        with TestClient(create_app()) as client:
            search = client.post(
                "/api/v1/knowledge/search",
                json={"course_id": self.course_id, "query": "AVL rotation", "top_k": 3},
            )
            self.assertEqual(search.status_code, 200)
            self.assertEqual(search.json()["results"], [])

            tutor = client.post(
                "/api/v1/tutor/ask",
                json={
                    "student_profile_id": self.profile_id,
                    "course_id": self.course_id,
                    "question": "AVL rotation",
                },
            )
            self.assertEqual(tutor.status_code, 200)
            tutor_body = tutor.json()
            self.assertEqual(tutor_body["source_refs"], [])
            tutor_run = client.get(f"/api/v1/agent-runs/{tutor_body['agent_run_id']}").json()
            tutor_step = next(step for step in tutor_run["steps"] if step["agent_type"] == "tutor")
            self.assertIn("Grounded sources: none retrieved.", tutor_step["decision_basis"])
            self.assertNotIn("document:", tutor_step["decision_basis"])

    def test_keyword_retrieval_handles_stack_queue_and_ranks_specific_chunk_first(self) -> None:
        with TestClient(create_app()) as client:
            bfs_document = self._ingest_bfs_document(client)
            stack_response = client.post(
                f"/api/v1/courses/{self.course_id}/documents",
                json={
                    "title": "stack-queue-note.md",
                    "source_type": "markdown",
                    "content": (
                        "# stack-queue\n"
                        "Stack uses push and pop with last-in-first-out behavior. "
                        "Queue uses enqueue and dequeue with first-in-first-out behavior. "
                        "BFS relies on queue while DFS commonly relies on stack or recursion."
                    ),
                },
            )
            self.assertEqual(stack_response.status_code, 200)
            stack_document = stack_response.json()["document"]

            search = client.post(
                "/api/v1/knowledge/search",
                json={"course_id": self.course_id, "query": "stack queue push pop enqueue dequeue", "top_k": 2},
            )
            self.assertEqual(search.status_code, 200)
            results = search.json()["results"]
            self.assertGreaterEqual(len(results), 1)
            self.assertEqual(results[0]["source_ref"], f"document:{stack_document['id']}#chunk:0")
            self.assertNotEqual(results[0]["source_ref"], f"document:{bfs_document['id']}#chunk:0")
            self.assertGreaterEqual(results[0]["metadata"]["term_match_count"], 4)

    def test_bfs_dfs_compare_query_retrieves_dfs_and_compare_chunks(self) -> None:
        with TestClient(create_app()) as client:
            document = self._ingest_bfs_dfs_coverage_document(client)
            search = client.post(
                "/api/v1/knowledge/search",
                json={
                    "course_id": self.course_id,
                    "query": "Why does BFS guarantee shortest path in an unweighted graph? Compare with DFS.",
                    "top_k": 3,
                },
            )
            self.assertEqual(search.status_code, 200)
            results = search.json()["results"]
            source_refs = [result["source_ref"] for result in results]
            contents = "\n".join(result["content"] for result in results)

            self.assertIn(f"document:{document['id']}#chunk:2", source_refs)
            self.assertIn(f"document:{document['id']}#chunk:3", source_refs)
            self.assertIn("DFS core idea", contents)
            self.assertIn("BFS vs DFS comparison", contents)
            compare_result = next(result for result in results if result["source_ref"] == f"document:{document['id']}#chunk:3")
            self.assertIn("dfs", compare_result["metadata"]["anchor_matches"])
            self.assertEqual(compare_result["metadata"]["coverage_bucket"], "bfs_dfs_compare")

    def test_chinese_mixed_bfs_dfs_query_terms_expand_to_retrieval_terms(self) -> None:
        service = KnowledgeBaseService()
        terms = service._query_terms("\u4e3a\u4ec0\u4e48BFS\u5728\u65e0\u6743\u56fe\u4e2d\u7b2c\u4e00\u6b21\u5230\u8fbe\u8282\u70b9\u5c31\u4ee3\u8868\u6700\u5c11\u8fb9\u6570\uff1f\u8bf7\u548cDFS\u5bf9\u6bd4\u3002")

        self.assertIn("bfs", terms)
        self.assertIn("dfs", terms)
        self.assertIn("\u65e0\u6743\u56fe", terms)
        self.assertIn("unweighted graph", terms)
        self.assertIn("shortest path", terms)
        self.assertIn("queue", terms)
        self.assertIn("stack", terms)

    def test_chinese_bfs_dfs_shortest_path_query_retrieves_english_chunks(self) -> None:
        with TestClient(create_app()) as client:
            document = self._ingest_bfs_dfs_coverage_document(client)
            search = client.post(
                "/api/v1/knowledge/search",
                json={
                    "course_id": self.course_id,
                    "query": "\u4e3a\u4ec0\u4e48BFS\u5728\u65e0\u6743\u56fe\u4e2d\u7b2c\u4e00\u6b21\u5230\u8fbe\u8282\u70b9\u5c31\u4ee3\u8868\u6700\u5c11\u8fb9\u6570\uff1f\u8bf7\u548cDFS\u5bf9\u6bd4\u3002",
                    "top_k": 3,
                },
            )
            self.assertEqual(search.status_code, 200)
            results = search.json()["results"]
            source_refs = {result["source_ref"] for result in results}

            self.assertIn(f"document:{document['id']}#chunk:2", source_refs)
            self.assertIn(f"document:{document['id']}#chunk:3", source_refs)
            self.assertTrue(any("unweighted graph" in result["metadata"]["matched_terms"] for result in results))

    def test_duplicate_bfs_dfs_documents_are_deduped_and_keep_coverage_diversity(self) -> None:
        with TestClient(create_app()) as client:
            first_document = self._ingest_bfs_dfs_coverage_document(client)
            self._ingest_bfs_dfs_coverage_document(client)
            self._ingest_bfs_dfs_coverage_document(client)

            search = client.post(
                "/api/v1/knowledge/search",
                json={
                    "course_id": self.course_id,
                    "query": "\u4e3a\u4ec0\u4e48BFS\u5728\u65e0\u6743\u56fe\u4e2d\u7b2c\u4e00\u6b21\u5230\u8fbe\u8282\u70b9\u5c31\u4ee3\u8868\u6700\u5c11\u8fb9\u6570\uff1f\u8bf7\u548cDFS\u5bf9\u6bd4\u3002",
                    "top_k": 5,
                },
            )
            self.assertEqual(search.status_code, 200)
            results = search.json()["results"]
            fingerprints = [result["metadata"]["content_fingerprint"] for result in results]
            buckets = {result["metadata"]["coverage_bucket"] for result in results}
            source_refs = {result["source_ref"] for result in results}

            self.assertEqual(len(fingerprints), len(set(fingerprints)))
            self.assertIn("bfs_dfs_compare", buckets)
            self.assertIn("bfs", buckets)
            self.assertIn("dfs", buckets)
            self.assertIn(f"document:{first_document['id']}#chunk:1", source_refs)
            self.assertIn(f"document:{first_document['id']}#chunk:2", source_refs)
            self.assertIn(f"document:{first_document['id']}#chunk:3", source_refs)

    def test_tutor_compare_question_source_refs_cover_dfs_or_compare_chunk(self) -> None:
        with TestClient(create_app()) as client:
            document = self._ingest_bfs_dfs_coverage_document(client)
            tutor = client.post(
                "/api/v1/tutor/ask",
                json={
                    "student_profile_id": self.profile_id,
                    "course_id": self.course_id,
                    "question": "Why does BFS guarantee shortest path in an unweighted graph? Compare with DFS.",
                },
            )
            self.assertEqual(tutor.status_code, 200)
            tutor_body = tutor.json()
            source_refs = {source["source_ref"] for source in tutor_body["source_refs"]}
            expected_refs = {
                f"document:{document['id']}#chunk:2",
                f"document:{document['id']}#chunk:3",
            }
            self.assertTrue(source_refs.intersection(expected_refs))
            tutor_run = client.get(f"/api/v1/agent-runs/{tutor_body['agent_run_id']}").json()
            tutor_step = next(step for step in tutor_run["steps"] if step["agent_type"] == "tutor")
            decision_basis = tutor_step["decision_basis"]
            self.assertIn("Grounded sources:", decision_basis)
            self.assertTrue(any(source_ref in decision_basis for source_ref in expected_refs))

    def test_tutor_chinese_bfs_dfs_question_returns_grounded_source_refs(self) -> None:
        with TestClient(create_app()) as client:
            document = self._ingest_bfs_dfs_coverage_document(client)
            tutor = client.post(
                "/api/v1/tutor/ask",
                json={
                    "student_profile_id": self.profile_id,
                    "course_id": self.course_id,
                    "question": "\u4e3a\u4ec0\u4e48BFS\u5728\u65e0\u6743\u56fe\u4e2d\u7b2c\u4e00\u6b21\u5230\u8fbe\u8282\u70b9\u5c31\u4ee3\u8868\u6700\u5c11\u8fb9\u6570\uff1f\u8bf7\u548cDFS\u5bf9\u6bd4\u3002",
                },
            )
            self.assertEqual(tutor.status_code, 200)
            tutor_body = tutor.json()
            source_refs = {source["source_ref"] for source in tutor_body["source_refs"]}
            self.assertIn(f"document:{document['id']}#chunk:3", source_refs)
            self.assertNotEqual(tutor_body["source_refs"], [])

    def _ingest_bfs_document(self, client: TestClient) -> dict:
        response = client.post(
            f"/api/v1/courses/{self.course_id}/documents",
            json={
                "title": "bfs-real-note.md",
                "source_type": "markdown",
                "content": (
                    "# bfs-dfs\n"
                    "BFS 使用 queue 按层扩展，适合无权图最短路径。"
                    "bfs-dfs 是当前学习路径节点的概念 slug。"
                ),
            },
        )
        self.assertEqual(response.status_code, 200)
        return response.json()["document"]

    def _ingest_bfs_dfs_coverage_document(self, client: TestClient) -> dict:
        response = client.post(
            f"/api/v1/courses/{self.course_id}/documents",
            json={
                "title": "bfs-dfs-coverage.md",
                "source_type": "markdown",
                "content": (
                    "# Overview\n"
                    "Graph traversal notes for exam review.\n"
                    "# BFS core idea\n"
                    "BFS uses a queue and explores by level. In an unweighted graph, the first time BFS reaches a node gives the fewest edge count from the start node.\n"
                    "# DFS core idea\n"
                    "DFS uses a stack or recursion and explores one branch deeply before backtracking. DFS does not guarantee shortest paths in an unweighted graph.\n"
                    "# BFS vs DFS comparison\n"
                    "BFS is preferred for shortest path in unweighted graphs because it expands level by level. DFS is preferred for depth-first traversal and backtracking, but it may reach a node through a longer route first.\n"
                ),
            },
        )
        self.assertEqual(response.status_code, 200)
        return response.json()["document"]

    def _seed_minimum_learning_records(self) -> tuple[int, int, int]:
        session = get_session_factory(self.database_url)()
        try:
            course = Course(title="Real RAG Course", description="真实 RAG 测试课程", is_demo=False)
            session.add(course)
            session.flush()

            concept = Concept(
                course_id=course.id,
                slug="bfs-dfs",
                name="BFS 与 DFS",
                chapter="Graph",
                description="图遍历",
                difficulty="basic",
            )
            session.add(concept)
            profile = StudentProfile(
                profile_type="weak_foundation",
                goal="掌握 BFS",
                level="beginner",
                preferences={"learning_preference": "step_by_step"},
                time_budget="每天 1 小时",
            )
            session.add(profile)
            session.flush()

            path = LearningPath(
                student_profile_id=profile.id,
                course_id=course.id,
                goal="学习 BFS",
                rationale="test",
                status="active",
            )
            session.add(path)
            session.flush()

            item = LearningPathItem(
                path_id=path.id,
                concept_id=concept.id,
                order_index=1,
                title="BFS",
                objective="理解 BFS 与无权图最短路径",
                rationale="test",
                status="pending",
            )
            session.add(item)
            session.commit()
            return course.id, profile.id, item.id
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
