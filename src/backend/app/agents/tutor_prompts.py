from typing import Protocol


class TutorEvidencePromptItem(Protocol):
    evidence_id: str
    content: str


def build_tutor_messages(
    question: str,
    evidence: list[TutorEvidencePromptItem],
    profile_summary: str,
    course_title: str,
) -> list[dict[str, str]]:
    context = "\n".join(f"{item.evidence_id}: {item.content}" for item in evidence)
    return [
        {
            "role": "system",
            "content": (
                "你是数据结构课程辅导教师。必须只使用给定 E1/E2/E3 证据，以简体中文回答。"
                "返回符合 schema 的 JSON，不要输出 Markdown。sections 必须依次包含 direct_answer、"
                "profile_adaptation、next_step。每节只能引用当前证据 ID，禁止输出 document:*、"
                "chunk:* 或任何内部来源标识。证据不足时明确说明缺少什么，不得编造事实。"
                "结合学生画像调整难度、练习方式与时间建议，整体简洁。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"课程：{course_title}\n学生画像：{profile_summary}\n问题：{question}\n"
                f"可用证据（只能引用其 E 编号）：\n{context}"
            ),
        },
    ]
