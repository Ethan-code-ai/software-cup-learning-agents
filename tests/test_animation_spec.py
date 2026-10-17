import unittest

from app.seed.demo_data import DEMO_CONCEPTS
from app.services.animation_spec_service import AnimationSpecService


class AnimationSpecServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = AnimationSpecService()

    def test_builds_binary_tree_traversal_spec_for_teaching_video(self) -> None:
        spec = self.service.build(
            concept_name="二叉树遍历",
            concept_slug="binary-tree-traversal",
            objective="掌握前序遍历的访问顺序",
            resource_type="teaching_video",
        )

        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertEqual(spec.version, "1.0")
        self.assertEqual(spec.template_id, "binary_tree_traversal")
        self.assertEqual(spec.data.traversal_type, "PRE_ORDER")
        self.assertEqual([node.id for node in spec.data.nodes], ["A", "B", "C", "D", "E"])
        self.assertEqual(
            [step.target for step in spec.timeline if step.action == "visit"],
            ["A", "B", "D", "E", "C"],
        )

    def test_timeline_targets_are_declared_nodes(self) -> None:
        spec = self.service.build(
            concept_name="二叉树遍历",
            concept_slug="binary-tree-traversal",
            objective="理解前序遍历",
            resource_type="teaching_video",
        )

        assert spec is not None
        node_ids = {node.id for node in spec.data.nodes}
        self.assertTrue(all(step.target in node_ids for step in spec.timeline))

    def test_defaults_to_preorder_when_objective_lists_multiple_traversals(self) -> None:
        spec = self.service.build(
            concept_name="二叉树遍历",
            concept_slug="binary-tree-traversal",
            objective="理解前序、中序、后序和层序遍历的差异",
            resource_type="teaching_video",
        )

        assert spec is not None
        self.assertEqual(spec.data.traversal_type, "PRE_ORDER")
        self.assertEqual([step.target for step in spec.timeline], ["A", "B", "D", "E", "C"])

    def test_non_video_resource_does_not_receive_animation_spec(self) -> None:
        spec = self.service.build(
            concept_name="二叉树遍历",
            concept_slug="binary-tree-traversal",
            objective="理解前序遍历",
            resource_type="guided_note",
        )

        self.assertIsNone(spec)

    def test_every_official_concept_builds_a_validated_animation_spec(self) -> None:
        specs = {
            concept["slug"]: self.service.build(
                concept_name=concept["name"],
                concept_slug=concept["slug"],
                objective=concept["description"],
                resource_type="teaching_video",
            )
            for concept in DEMO_CONCEPTS
        }

        self.assertEqual(len(specs), 24)
        self.assertTrue(all(spec is not None for spec in specs.values()))
        self.assertGreaterEqual(len({spec.template_id for spec in specs.values() if spec}), 8)
        for concept_slug, spec in specs.items():
            assert spec is not None, concept_slug
            self.assertGreater(len(spec.data.nodes), 0, concept_slug)
            self.assertGreater(len(spec.timeline), 0, concept_slug)

    def test_unknown_video_topic_uses_safe_fallback_without_raw_svg(self) -> None:
        spec = self.service.build(
            concept_name="红黑树旋转",
            concept_slug="red-black-tree",
            objective="理解旋转",
            resource_type="teaching_video",
        )

        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertEqual(spec.template_id, "concept_fallback")
        self.assertNotIn("<svg", spec.model_dump_json().lower())

    def test_bfs_dfs_exposes_distinct_queue_and_stack_traces(self) -> None:
        spec = self.service.build(
            concept_name="BFS/DFS",
            concept_slug="bfs-dfs",
            objective="比较广度优先搜索和深度优先搜索",
            resource_type="teaching_video",
        )

        assert spec is not None
        variants = {variant.id: variant for variant in spec.data.variants}
        self.assertEqual(set(variants), {"bfs", "dfs"})
        self.assertEqual(variants["bfs"].structure_label, "Queue 队列")
        self.assertEqual(variants["dfs"].structure_label, "Stack 栈")
        self.assertEqual([step.target for step in variants["bfs"].timeline], ["gA", "gB", "gC", "gD", "gE"])
        self.assertEqual([step.target for step in variants["dfs"].timeline], ["gA", "gB", "gD", "gE", "gC"])
        self.assertTrue(all(step.frontier for step in variants["bfs"].timeline[:-1]))
        self.assertNotEqual(
            [step.frontier for step in variants["bfs"].timeline],
            [step.frontier for step in variants["dfs"].timeline],
        )

    def test_every_template_family_contains_real_state_changes(self) -> None:
        slugs = [
            "complexity-analysis",
            "linked-list",
            "stack",
            "tree-basics",
            "shortest-path",
            "search-basics",
            "simple-sorts",
            "algorithm-design",
        ]

        specs = [
            self.service.build(
                concept_name=next(item["name"] for item in DEMO_CONCEPTS if item["slug"] == slug),
                concept_slug=slug,
                objective=next(item["description"] for item in DEMO_CONCEPTS if item["slug"] == slug),
                resource_type="teaching_video",
            )
            for slug in slugs
        ]

        for slug, spec in zip(slugs, specs, strict=True):
            assert spec is not None
            signatures = {
                (
                    tuple(sorted(step.values.items())),
                    tuple(sorted(step.labels.items())),
                    tuple(step.frontier),
                    tuple(step.visited),
                    step.range_start,
                    step.range_end,
                )
                for step in spec.timeline
            }
            self.assertGreater(len(signatures), 1, slug)

    def test_stack_and_queue_show_mutating_lifo_and_fifo_operations(self) -> None:
        stack = self.service.build(
            concept_name="栈",
            concept_slug="stack",
            objective="理解 LIFO 与 push/pop",
            resource_type="teaching_video",
        )
        queue = self.service.build(
            concept_name="队列",
            concept_slug="queue",
            objective="理解 FIFO 与 enqueue/dequeue",
            resource_type="teaching_video",
        )

        assert stack is not None and queue is not None
        self.assertEqual(stack.data.structure_label, "Stack 栈")
        self.assertEqual(queue.data.structure_label, "Queue 队列")
        self.assertIn("push", {step.action for step in stack.timeline})
        self.assertIn("pop", {step.action for step in stack.timeline})
        self.assertIn("enqueue", {step.action for step in queue.timeline})
        self.assertIn("dequeue", {step.action for step in queue.timeline})
        self.assertEqual(stack.timeline[-1].frontier, ["s0", "s1", "s2"])
        self.assertEqual(queue.timeline[-1].frontier, ["s1", "s2", "s3"])


if __name__ == "__main__":
    unittest.main()
