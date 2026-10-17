from collections.abc import Sequence

from app.schemas import (
    AnimationEdge,
    AnimationNode,
    AnimationSceneData,
    AnimationSpecResponse,
    AnimationTimelineStep,
    AnimationVariant,
)


TEMPLATE_BY_CONCEPT: dict[str, str] = {
    "complexity-analysis": "complexity_visualizer",
    "asymptotic-notation": "complexity_visualizer",
    "recurrence-analysis": "complexity_visualizer",
    "complexity-practice": "complexity_visualizer",
    "array-list": "linear_structure",
    "linked-list": "linear_structure",
    "linear-list-comparison": "linear_structure",
    "stack": "stack_queue_operations",
    "queue": "stack_queue_operations",
    "recursion": "stack_queue_operations",
    "tree-basics": "tree_visualizer",
    "binary-tree": "tree_visualizer",
    "binary-tree-traversal": "binary_tree_traversal",
    "search-tree": "tree_visualizer",
    "graph-representation": "graph_visualizer",
    "bfs-dfs": "graph_visualizer",
    "shortest-path": "graph_visualizer",
    "search-basics": "search_visualizer",
    "hash-table": "search_visualizer",
    "sorting-basics": "sorting_visualizer",
    "simple-sorts": "sorting_visualizer",
    "efficient-sorts": "sorting_visualizer",
    "algorithm-design": "algorithm_workflow",
    "data-structure-project": "algorithm_workflow",
}


class AnimationSpecService:
    """Build validated, server-owned animation scenes for every course concept."""

    def build(
        self,
        *,
        concept_name: str,
        concept_slug: str,
        objective: str,
        resource_type: str,
    ) -> AnimationSpecResponse | None:
        if resource_type != "teaching_video":
            return None

        template_id = TEMPLATE_BY_CONCEPT.get(concept_slug, "concept_fallback")
        if template_id == "binary_tree_traversal":
            return self._binary_tree_traversal(concept_name, concept_slug, objective)
        builders = {
            "complexity_visualizer": self._complexity,
            "linear_structure": self._linear_structure,
            "stack_queue_operations": self._stack_queue,
            "tree_visualizer": self._tree,
            "graph_visualizer": self._graph,
            "search_visualizer": self._search,
            "sorting_visualizer": self._sorting,
            "algorithm_workflow": self._workflow,
            "concept_fallback": self._fallback,
        }
        return builders[template_id](concept_name, concept_slug, objective)

    def _complexity(self, name: str, slug: str, objective: str) -> AnimationSpecResponse:
        labels = {
            "recurrence-analysis": ["T(1)", "T(n/2)", "T(n)", "合并"],
            "complexity-practice": ["常数项", "单循环", "嵌套循环", "优化后"],
        }.get(slug, ["O(1)", "O(log n)", "O(n)", "O(n²)"])
        values = [18, 34, 58, 88]
        nodes = [
            AnimationNode(id=f"c{i}", label=label, x=100 + i * 140, y=290 - value * 2, value=value, kind="bar")
            for i, (label, value) in enumerate(zip(labels, values, strict=True))
        ]
        samples = [
            ("n = 2", [12, 18, 24, 36]),
            ("n = 4", [12, 28, 42, 64]),
            ("n = 8", [12, 38, 66, 98]),
            ("n = 16", [12, 48, 92, 150]),
        ]
        timeline = [
            AnimationTimelineStep(
                at_ms=i * 1000,
                action="compare",
                target=f"c{min(i, 3)}",
                caption=f"输入规模扩大到 {sample_label}，比较各增长率",
                values={f"c{index}": value for index, value in enumerate(sample_values)},
                visited=[f"c{index}" for index in range(4)],
            )
            for i, (sample_label, sample_values) in enumerate(samples)
        ]
        return self._spec("complexity_visualizer", name, objective, slug, nodes, [], timeline, "增长率")

    def _linear_structure(self, name: str, slug: str, objective: str) -> AnimationSpecResponse:
        labels = ["head", "12", "26", "39", "null"] if slug == "linked-list" else ["0:12", "1:26", "2:39", "3:空", "容量4"]
        nodes = [AnimationNode(id=f"l{i}", label=label, x=82 + i * 118, y=172, kind="cell") for i, label in enumerate(labels)]
        edges = [AnimationEdge(source=f"l{i}", target=f"l{i + 1}") for i in range(len(nodes) - 1)] if slug != "array-list" else []
        if slug == "linked-list":
            states = [
                ("highlight", "l1", "初始链表：12 → 26 → 39", ["head", "12", "26", "39", "null"]),
                ("select", "l2", "定位插入点：在 12 与 26 之间插入 18", ["head", "12", "插入18", "26", "39"]),
                ("complete", "l2", "修改前驱指针，链表完成插入", ["head", "12", "18", "26", "39"]),
            ]
        else:
            states = [
                ("highlight", "l2", "初始顺序表已使用 3 个位置", ["0:12", "1:26", "2:39", "3:空", "容量4"]),
                ("select", "l3", "为插入 18 腾出位置，39 向后移动", ["0:12", "1:26", "2:空", "3:39", "容量4"]),
                ("complete", "l2", "18 写入空位，顺序表插入完成", ["0:12", "1:26", "2:18", "3:39", "容量4"]),
            ]
        timeline = [
            AnimationTimelineStep(
                at_ms=i * 1100,
                action=action,
                target=target,
                caption=caption,
                labels={f"l{index}": label for index, label in enumerate(state_labels)},
                visited=[f"l{index}" for index in range(min(i + 2, 5))],
            )
            for i, (action, target, caption, state_labels) in enumerate(states)
        ]
        return self._spec("linear_structure", name, objective, slug, nodes, edges, timeline, "结构状态")

    def _stack_queue(self, name: str, slug: str, objective: str) -> AnimationSpecResponse:
        if slug == "queue":
            labels, positions, structure_label = ["8", "13", "21", "34"], [(110 + i * 135, 172) for i in range(4)], "Queue 队列"
            states = [
                ("highlight", "s0", "初始队列：Front 指向 8，Rear 指向 13", ["s0", "s1"]),
                ("enqueue", "s2", "enqueue(21)：21 从 Rear 端进入队列", ["s0", "s1", "s2"]),
                ("enqueue", "s3", "enqueue(34)：34 成为新的 Rear", ["s0", "s1", "s2", "s3"]),
                ("dequeue", "s0", "dequeue()：最早进入的 8 从 Front 端离开", ["s1", "s2", "s3"]),
            ]
        elif slug == "recursion":
            labels, positions, structure_label = ["f(1)", "f(2)", "f(3)", "f(4)"], [(320, 270 - i * 62) for i in range(4)], "Call Stack 调用栈"
            states = [
                ("push", "s0", "调用 f(1)，建立第一个栈帧", ["s0"]),
                ("push", "s1", "递归调用 f(2)，新栈帧压栈", ["s0", "s1"]),
                ("push", "s2", "递归调用 f(3)，继续压栈", ["s0", "s1", "s2"]),
                ("pop", "s2", "命中递归基，栈帧开始依次返回", ["s0", "s1"]),
            ]
        else:
            labels, positions, structure_label = ["8", "13", "21", "34"], [(320, 270 - i * 62) for i in range(4)], "Stack 栈"
            states = [
                ("highlight", "s1", "初始栈：8 在栈底，13 位于 Top", ["s0", "s1"]),
                ("push", "s2", "push(21)：21 从 Top 端压入", ["s0", "s1", "s2"]),
                ("push", "s3", "push(34)：34 成为新的 Top", ["s0", "s1", "s2", "s3"]),
                ("pop", "s3", "pop()：最后压入的 34 最先弹出", ["s0", "s1", "s2"]),
            ]
        nodes = [AnimationNode(id=f"s{i}", label=label, x=x, y=y, kind=slug) for i, (label, (x, y)) in enumerate(zip(labels, positions, strict=True))]
        timeline = [
            AnimationTimelineStep(
                at_ms=i * 1100,
                action=action,
                target=target,
                caption=caption,
                frontier=frontier,
                visited=frontier,
            )
            for i, (action, target, caption, frontier) in enumerate(states)
        ]
        return self._spec("stack_queue_operations", name, objective, slug, nodes, [], timeline, structure_label)

    def _tree(self, name: str, slug: str, objective: str) -> AnimationSpecResponse:
        labels = ["8", "4", "12", "2", "6"] if slug == "search-tree" else ["根", "左子树", "右子树", "叶 A", "叶 B"]
        nodes, edges = _tree_scene(labels)
        order = ["A", "B", "D", "E", "C"]
        timeline = _visit_timeline(order, "visit", "沿父子关系展开树结构")
        return self._spec("tree_visualizer", name, objective, slug, nodes, edges, timeline, "树节点")

    def _binary_tree_traversal(self, name: str, slug: str, objective: str) -> AnimationSpecResponse:
        traversal_type, order = _traversal_order(" ".join([name, slug, objective]).lower())
        nodes, edges = _tree_scene(["A", "B", "C", "D", "E"])
        captions = {
            "A": "从根节点 A 开始",
            "B": "进入 A 的左子树，访问 B",
            "C": "左子树完成后访问右子树 C",
            "D": "继续访问 B 的左孩子 D",
            "E": "再访问 B 的右孩子 E",
        }
        timeline = [
            AnimationTimelineStep(
                at_ms=i * 1100,
                action="visit",
                target=node_id,
                caption=captions[node_id],
                visited=order[: i + 1],
            )
            for i, node_id in enumerate(order)
        ]
        return AnimationSpecResponse(
            template_id="binary_tree_traversal",
            title=f"{name} · {_traversal_label(traversal_type)}",
            description=objective,
            duration_ms=len(timeline) * 1100,
            data=AnimationSceneData(mode=slug, structure_label="访问序列", traversal_type=traversal_type, nodes=nodes, edges=edges, sequence=order),
            timeline=timeline,
        )

    def _graph(self, name: str, slug: str, objective: str) -> AnimationSpecResponse:
        nodes = [
            AnimationNode(id="gA", label="A", x=110, y=165), AnimationNode(id="gB", label="B", x=255, y=72),
            AnimationNode(id="gC", label="C", x=255, y=258), AnimationNode(id="gD", label="D", x=430, y=105),
            AnimationNode(id="gE", label="E", x=520, y=230),
        ]
        weighted_edges = [("gA", "gB", "2"), ("gA", "gC", "4"), ("gB", "gD", "3"), ("gC", "gE", "6"), ("gD", "gE", "2")]
        edges = [AnimationEdge(source=a, target=b, label=None if slug == "bfs-dfs" else w) for a, b, w in weighted_edges]
        if slug == "bfs-dfs":
            bfs = _graph_trace(
                ["gA", "gB", "gC", "gD", "gE"],
                [["gB", "gC"], ["gC", "gD"], ["gD", "gE"], ["gE"], []],
                "Queue 队列",
            )
            dfs = _graph_trace(
                ["gA", "gB", "gD", "gE", "gC"],
                [["gC", "gB"], ["gC", "gD"], ["gC", "gE"], ["gC"], []],
                "Stack 栈",
            )
            variants = [
                AnimationVariant(id="bfs", label="BFS 广度优先", structure_label="Queue 队列", timeline=bfs),
                AnimationVariant(id="dfs", label="DFS 深度优先", structure_label="Stack 栈", timeline=dfs),
            ]
            return self._spec("graph_visualizer", name, objective, slug, nodes, edges, bfs, "Queue 队列", variants)
        if slug == "shortest-path":
            distances = [
                {"gA": 0, "gB": 99, "gC": 99, "gD": 99, "gE": 99},
                {"gA": 0, "gB": 2, "gC": 4, "gD": 99, "gE": 99},
                {"gA": 0, "gB": 2, "gC": 4, "gD": 5, "gE": 99},
                {"gA": 0, "gB": 2, "gC": 4, "gD": 5, "gE": 7},
            ]
            targets = ["gA", "gB", "gD", "gE"]
            timeline = [
                AnimationTimelineStep(at_ms=i * 1100, action="relax", target=target, caption=f"松弛边后更新距离：当前处理 {target[-1]}", values=values, visited=targets[: i + 1])
                for i, (target, values) in enumerate(zip(targets, distances, strict=True))
            ]
            return self._spec("graph_visualizer", name, objective, slug, nodes, edges, timeline, "最短距离")
        timeline = _visit_timeline(["gA", "gB", "gC", "gD", "gE"], "visit", "读取邻接关系")
        return self._spec("graph_visualizer", name, objective, slug, nodes, edges, timeline, "邻接关系")

    def _search(self, name: str, slug: str, objective: str) -> AnimationSpecResponse:
        labels = ["0:18", "1:空", "2:42", "3:27", "4:空", "5:35"] if slug == "hash-table" else ["3", "8", "12", "19", "27", "35"]
        nodes = [AnimationNode(id=f"q{i}", label=label, x=66 + i * 96, y=170, value=i, kind="bucket") for i, label in enumerate(labels)]
        if slug == "hash-table":
            order = ["q2", "q3", "q5"]
            timeline = _visit_timeline(order, "select", "按哈希地址探测桶位")
        else:
            states = [("q2", 0, 5, "中点 12 小于目标 19，舍弃左半区"), ("q4", 3, 5, "中点 27 大于目标 19，舍弃右半区"), ("q3", 3, 3, "中点命中目标 19")]
            timeline = [
                AnimationTimelineStep(at_ms=i * 1100, action="select", target=target, caption=caption, range_start=start, range_end=end, visited=[item[0] for item in states[: i + 1]])
                for i, (target, start, end, caption) in enumerate(states)
            ]
        return self._spec("search_visualizer", name, objective, slug, nodes, [], timeline, "查找区间")

    def _sorting(self, name: str, slug: str, objective: str) -> AnimationSpecResponse:
        values = [46, 18, 72, 31, 58, 24]
        nodes = [AnimationNode(id=f"b{i}", label=str(value), x=72 + i * 95, y=300 - value * 2, value=value, kind="bar") for i, value in enumerate(values)]
        states = [
            [46, 18, 72, 31, 58, 24],
            [18, 46, 72, 31, 58, 24],
            [18, 46, 31, 72, 58, 24],
            [18, 46, 31, 58, 72, 24],
            [18, 46, 31, 58, 24, 72],
        ]
        targets = ["b0", "b1", "b2", "b3", "b4"]
        timeline = [
            AnimationTimelineStep(
                at_ms=i * 900,
                action="compare" if i == 0 else "swap",
                target=target,
                caption="读取初始序列" if i == 0 else f"比较相邻元素并交换，第 {i} 次状态更新",
                values={f"b{index}": value for index, value in enumerate(state)},
                visited=targets[: i + 1],
            )
            for i, (target, state) in enumerate(zip(targets, states, strict=True))
        ]
        return self._spec("sorting_visualizer", name, objective, slug, nodes, [], timeline, "当前序列")

    def _workflow(self, name: str, slug: str, objective: str) -> AnimationSpecResponse:
        labels = ["问题建模", "结构选择", "算法实现", "测试验证"] if slug == "data-structure-project" else ["分解问题", "选择策略", "证明正确", "分析复杂度"]
        nodes = [AnimationNode(id=f"w{i}", label=label, x=95 + i * 145, y=172, kind="stage") for i, label in enumerate(labels)]
        edges = [AnimationEdge(source=f"w{i}", target=f"w{i + 1}") for i in range(len(nodes) - 1)]
        timeline = _visit_timeline([f"w{i}" for i in range(4)], "complete", "完成当前阶段并进入下一阶段")
        return self._spec("algorithm_workflow", name, objective, slug, nodes, edges, timeline, "完成阶段")

    def _fallback(self, name: str, slug: str, objective: str) -> AnimationSpecResponse:
        labels = [name[:18], "核心概念", "典型示例", "自我检查"]
        nodes = [
            AnimationNode(id="f0", label=labels[0], x=320, y=165, kind="focus"),
            AnimationNode(id="f1", label=labels[1], x=120, y=80),
            AnimationNode(id="f2", label=labels[2], x=520, y=80),
            AnimationNode(id="f3", label=labels[3], x=320, y=280),
        ]
        edges = [AnimationEdge(source="f0", target=f"f{i}") for i in range(1, 4)]
        timeline = _visit_timeline(["f0", "f1", "f2", "f3"], "highlight", "逐步建立概念理解")
        return self._spec("concept_fallback", name, objective, slug, nodes, edges, timeline, "概念要点")

    @staticmethod
    def _spec(
        template_id: str,
        name: str,
        objective: str,
        mode: str,
        nodes: list[AnimationNode],
        edges: list[AnimationEdge],
        timeline: list[AnimationTimelineStep],
        structure_label: str,
        variants: list[AnimationVariant] | None = None,
    ) -> AnimationSpecResponse:
        return AnimationSpecResponse(
            template_id=template_id,
            title=f"{name} · 交互演示",
            description=objective,
            duration_ms=max(1000, len(timeline) * 1000),
            data=AnimationSceneData(
                mode=mode,
                structure_label=structure_label,
                nodes=nodes,
                edges=edges,
                sequence=[node.id for node in nodes],
                variants=variants or [],
            ),
            timeline=timeline,
        )


def _tree_scene(labels: Sequence[str]) -> tuple[list[AnimationNode], list[AnimationEdge]]:
    positions = [(320, 54), (188, 148), (452, 148), (122, 254), (254, 254)]
    ids = ["A", "B", "C", "D", "E"]
    nodes = [AnimationNode(id=node_id, label=label, x=x, y=y, kind="tree") for node_id, label, (x, y) in zip(ids, labels, positions, strict=True)]
    edges = [AnimationEdge(source=a, target=b) for a, b in [("A", "B"), ("A", "C"), ("B", "D"), ("B", "E")]]
    return nodes, edges


def _visit_timeline(order: list[str], action: str, caption_prefix: str) -> list[AnimationTimelineStep]:
    return [
        AnimationTimelineStep(
            at_ms=i * 1000,
            action=action,
            target=node_id,
            caption=f"{caption_prefix}：{node_id[-1]}",
            visited=order[: i + 1],
        )
        for i, node_id in enumerate(order)
    ]


def _graph_trace(order: list[str], frontiers: list[list[str]], structure_label: str) -> list[AnimationTimelineStep]:
    return [
        AnimationTimelineStep(
            at_ms=i * 1100,
            action="dequeue" if structure_label.startswith("Queue") else "pop",
            target=node_id,
            caption=f"从 {structure_label} 取出 {node_id[-1]}，加入已访问集合",
            frontier=frontier,
            visited=order[: i + 1],
        )
        for i, (node_id, frontier) in enumerate(zip(order, frontiers, strict=True))
    ]


def _traversal_order(topic: str) -> tuple[str, list[str]]:
    orders = {
        "PRE_ORDER": (("前序", "pre-order", "preorder"), ["A", "B", "D", "E", "C"]),
        "IN_ORDER": (("中序", "in-order", "inorder"), ["D", "B", "E", "A", "C"]),
        "POST_ORDER": (("后序", "post-order", "postorder"), ["D", "E", "B", "C", "A"]),
        "LEVEL_ORDER": (("层序", "level-order", "levelorder"), ["A", "B", "C", "D", "E"]),
    }
    matched = [(name, order) for name, (tokens, order) in orders.items() if any(token in topic for token in tokens)]
    return matched[0] if len(matched) == 1 else ("PRE_ORDER", orders["PRE_ORDER"][1])


def _traversal_label(traversal_type: str) -> str:
    return {"PRE_ORDER": "前序遍历", "IN_ORDER": "中序遍历", "POST_ORDER": "后序遍历", "LEVEL_ORDER": "层序遍历"}[traversal_type]
