from dataclasses import dataclass, field
from typing import Any

from app.schemas import KnowledgeSearchResult
from app.services.citation_service import source_ref_payload


@dataclass(frozen=True)
class ResourceAgentResult:
    content: str
    source_refs: list[dict[str, Any]]
    input_summary: str
    output_summary: str
    decision_basis: str
    execution_mode: str = "rule_based"
    provider: str = "rule_based"
    model: str = ""
    fallback_used: bool = False
    fallback_reason: str | None = None
    duration_ms: int = 0
    provider_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TutorAgentResult:
    answer: str
    source_refs: list[dict[str, Any]]
    input_summary: str
    output_summary: str
    decision_basis: str
    execution_mode: str = "rule_based"
    provider: str = "rule_based"
    model: str = ""
    fallback_used: bool = False
    fallback_reason: str | None = None
    duration_ms: int = 0
    provider_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class QuizAgentResult:
    question: str
    answer: str
    explanation: str
    concept_tags: list[str]
    input_summary: str
    output_summary: str
    decision_basis: str
    question_type: str = "short_answer"
    options: list[str] = field(default_factory=list)
    source_refs: list[dict[str, Any]] = field(default_factory=list)
    execution_mode: str = "rule_based"
    provider: str = "rule_based"
    model: str = ""
    fallback_used: bool = False
    fallback_reason: str | None = None
    duration_ms: int = 0
    provider_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvaluatorAgentResult:
    score: float
    feedback: str
    mastery_updates: list[dict[str, Any]]
    input_summary: str
    output_summary: str
    decision_basis: str
    execution_mode: str = "rule_based"
    provider: str = "rule_based"
    model: str = ""
    fallback_used: bool = False
    fallback_reason: str | None = None
    duration_ms: int = 0
    provider_metadata: dict[str, Any] = field(default_factory=dict)


class RuleBasedResourceAgent:
    SUPPORTED_RESOURCE_TYPES = {
        "guided_note": "讲解文档",
        "practice_questions": "练习题",
        "mind_map": "思维导图",
        "extended_reading": "拓展阅读",
        "coding_case": "代码实操案例",
        "teaching_video": "教学动画脚本",
    }

    def generate(
        self,
        concept_name: str,
        objective: str,
        resource_type: str,
        chunks: list[KnowledgeSearchResult],
        profile_preferences: dict[str, Any] | None = None,
    ) -> ResourceAgentResult:
        normalized_type = resource_type if resource_type in self.SUPPORTED_RESOURCE_TYPES else "guided_note"
        source_refs = self._source_refs(chunks)
        if not chunks:
            return ResourceAgentResult(
                content=(
                    f"【资料不足】暂不生成“{concept_name}”的{self.SUPPORTED_RESOURCE_TYPES[normalized_type]}。\n"
                    "当前请求没有通过安全校验的课程资料，继续生成可能造成无依据扩写。请先上传或补充课程资料后重试。"
                ),
                source_refs=[],
                input_summary=f"为知识点 {concept_name} 生成 {self.SUPPORTED_RESOURCE_TYPES[normalized_type]} 资源。",
                output_summary="课程资料不足，返回安全限制说明，未生成事实性学习内容。",
                decision_basis="无可用 Retriever chunk 时不编造资源，也不生成伪造 source_ref。",
            )
        evidence = chunks[0].content if chunks else "暂无可用资料片段。"
        preferences = profile_preferences or {}
        style = str(preferences.get("learning_preference") or preferences.get("style") or "step_by_step")
        weak_points = str(preferences.get("weak_points") or "待通过测验进一步定位")
        content = self._render_resource(normalized_type, concept_name, objective, evidence, style, weak_points)
        return ResourceAgentResult(
            content=content,
            source_refs=source_refs,
            input_summary=f"为知识点 {concept_name} 生成 {self.SUPPORTED_RESOURCE_TYPES[normalized_type]} 资源。",
            output_summary=f"生成 {self.SUPPORTED_RESOURCE_TYPES[normalized_type]}，包含资料依据和个性化建议。",
            decision_basis="基于学习路径节点目标、学生画像偏好和课程资料 chunk 生成资源，避免无依据扩写。",
        )

    def _render_resource(
        self,
        resource_type: str,
        concept_name: str,
        objective: str,
        evidence: str,
        style: str,
        weak_points: str,
    ) -> str:
        title = self.SUPPORTED_RESOURCE_TYPES[resource_type]
        if resource_type == "teaching_video":
            return (
                f"【{title}】{concept_name}\n"
                f"学习目标：{objective}\n"
                f"资料依据：{evidence}\n"
                "分镜 1：展示完整数据结构，说明本次动画的观察目标。\n"
                "分镜 2：按照算法顺序逐步高亮当前节点，并保留已访问轨迹。\n"
                "分镜 3：汇总访问顺序，提示学生暂停后自行复述。\n"
                f"个性化提示：采用 {style} 节奏，每一步只解释一个状态变化。"
            )
        if resource_type == "practice_questions":
            return (
                f"【{title}】{concept_name}\n"
                f"学习目标：{objective}\n"
                f"资料依据：{evidence}\n"
                f"画像侧重点：{weak_points}\n"
                "题目 1：用自己的话说明该知识点的核心思想。\n"
                "题目 2：结合一个数据结构操作场景说明它的作用。\n"
                "题目 3：写出一个容易混淆点，并给出区分方法。\n"
                "建议：先独立作答，再回到 Tutor 区域追问不确定点。"
            )
        if resource_type == "mind_map":
            return (
                f"【{title}】{concept_name}\n"
                f"- 中心主题：{concept_name}\n"
                f"  - 学习目标：{objective}\n"
                f"  - 资料依据：{evidence}\n"
                f"  - 关键概念：定义、适用场景、基本操作\n"
                f"  - 薄弱点关注：{weak_points}\n"
                "  - 练习路径：复述概念 -> 对比场景 -> 完成小测 -> 复盘错误"
            )
        if resource_type == "extended_reading":
            return (
                f"【{title}】{concept_name}\n"
                f"学习目标：{objective}\n"
                f"先读资料依据：{evidence}\n"
                "拓展阅读建议：\n"
                "1. 查阅教材中该知识点的定义和图示。\n"
                "2. 对比同章节相邻知识点，找出使用边界。\n"
                "3. 记录一个实际题目中该知识点的触发信号。\n"
                f"阅读方式：按 {style} 风格做短笔记，不追求一次读完。"
            )
        if resource_type == "coding_case":
            return (
                f"【{title}】{concept_name}\n"
                f"学习目标：{objective}\n"
                f"资料依据：{evidence}\n"
                "实操任务：\n"
                "1. 写出核心数据结构或算法过程的伪代码。\n"
                "2. 准备一个最小输入样例并手动跟踪状态变化。\n"
                "3. 标注时间复杂度和一个常见边界条件。\n"
                "```python\n"
                "from collections import deque\n\n"
                "def bfs(graph, start):\n"
                "    visited = {start}\n"
                "    queue = deque([start])\n"
                "    order = []\n"
                "    while queue:\n"
                "        node = queue.popleft()\n"
                "        order.append(node)\n"
                "        for neighbor in graph.get(node, []):\n"
                "            if neighbor not in visited:\n"
                "                visited.add(neighbor)\n"
                "                queue.append(neighbor)\n"
                "    return order\n\n"
                "print(bfs({'A': ['B', 'C'], 'B': ['D'], 'C': [], 'D': []}, 'A'))\n"
                "```\n"
                "输入样例：A -> B, C; B -> D。\n"
                "预期输出：['A', 'B', 'C', 'D']。\n"
                f"个性化提醒：如果薄弱点包含 {concept_name}，先完成手动跟踪再写代码。"
            )
        return (
            f"【{title}】{concept_name}\n"
            f"学习目标：{objective}\n"
            f"核心讲解：{evidence}\n"
            f"画像侧重点：{weak_points}\n"
            f"学习方式：采用 {style} 风格，先理解定义，再用一个小例子验证。\n"
            "练习建议：先复述概念，再完成 1 道基础题和 1 道应用题。"
        )

    def _source_refs(self, chunks: list[KnowledgeSearchResult]) -> list[dict[str, Any]]:
        return [source_ref_payload(chunk) for chunk in chunks]


class RuleBasedTutorAgent:
    def answer(
        self,
        question: str,
        chunks: list[KnowledgeSearchResult],
        profile_summary: str = "",
        course_title: str = "",
    ) -> TutorAgentResult:
        source_refs = [source_ref_payload(chunk) for chunk in chunks]
        if chunks:
            evidence = chunks[0].content
            answer = f"根据课程资料：{evidence} 针对你的问题“{question}”，建议先抓住资料中的定义和适用场景，再做一个小例子验证理解。"
        else:
            answer = f"暂未检索到足够资料回答“{question}”，建议先加载数据结构 demo data 或补充课程资料。"
        return TutorAgentResult(
            answer=answer,
            source_refs=source_refs,
            input_summary=f"回答学生问题：{question}",
            output_summary="返回基于课程资料片段的回答和引用线索。",
            decision_basis="优先使用 KnowledgeBaseService 返回的 chunk 和 source_ref 形成 grounded answer。",
        )


class RuleBasedQuizAgent:
    def generate(
        self,
        concept_name: str,
        difficulty: str,
        chunk: KnowledgeSearchResult | list[KnowledgeSearchResult] | None,
        _quiz_context: Any | None = None,
    ) -> QuizAgentResult:
        if isinstance(chunk, list):
            chunks = chunk
            chunk = chunks[0] if chunks else None
        else:
            chunks = [chunk] if chunk is not None else []
        evidence_context = chunk.content if chunk else f"{concept_name} 是当前数据结构 MVP 知识点。"
        question = f"【{difficulty}】请说明{concept_name}的核心思想，并结合一个数据结构场景说明其作用。"
        answer = f"应围绕{concept_name}的定义、适用场景和基本操作说明。"
        explanation = f"解析依据：{evidence_context}"
        return QuizAgentResult(
            question=question,
            answer=answer,
            explanation=explanation,
            concept_tags=[concept_name],
            input_summary=f"为知识点 {concept_name} 生成 {difficulty} 难度题目。",
            output_summary="生成 1 道包含答案、解析和知识点标签的小测题。",
            decision_basis="题目绑定 concept_id 和 difficulty，并使用课程资料 chunk 作为解析依据。",
            source_refs=[source_ref_payload(item) for item in chunks if item.source_ref],
        )


class RuleBasedEvaluatorAgent:
    def evaluate(self, expected_answer: str, answers: dict[str, Any], concept_id: int) -> EvaluatorAgentResult:
        submitted_text = " ".join(str(value) for value in answers.values()).strip()
        expected_terms = {term for term in expected_answer.replace("，", " ").replace("。", " ").split() if term}
        matched_terms = {term for term in expected_terms if term in submitted_text}
        score = 1.0 if submitted_text and matched_terms else (0.6 if submitted_text else 0.0)
        if score >= 1.0:
            feedback = "回答覆盖了关键点，建议继续做应用题巩固。"
        elif score > 0:
            feedback = "回答有一定相关性，但关键概念或应用场景不完整，建议回看讲解并补充例子。"
        else:
            feedback = "未检测到有效作答，建议先复习该知识点的定义和基本应用。"
        mastery_score = min(1.0, max(0.0, score))
        return EvaluatorAgentResult(
            score=score,
            feedback=feedback,
            mastery_updates=[
                {
                    "concept_id": concept_id,
                    "mastery_score": mastery_score,
                    "evidence": {"matched_terms": sorted(matched_terms), "submitted_length": len(submitted_text)},
                }
            ],
            input_summary=f"评价 concept_id={concept_id} 的一次作答。",
            output_summary=f"评分 {score:.2f}，生成反馈和掌握度更新建议。",
            decision_basis="基于标准答案关键词覆盖和作答是否为空做 MVP rule-based 评价。",
        )
