from app.core.enums import ProfileType
from app.schemas import StudentProfileCreate, StudentProfileDialogueCreate


PROFILE_DIMENSION_KEYS = [
    "learning_goal",
    "foundation_level",
    "learning_preference",
    "available_time",
    "weak_points",
    "resource_preference",
]


def normalize_profile_dimensions(profile: StudentProfileCreate) -> StudentProfileCreate:
    preferences = dict(profile.preferences)
    preferences.setdefault("profile_origin", "user_created")
    preferences.setdefault("learning_goal", profile.goal)
    preferences.setdefault("foundation_level", profile.level)
    preferences.setdefault("learning_preference", preferences.get("style", "step_by_step"))
    preferences.setdefault("available_time", profile.time_budget)
    preferences.setdefault("weak_points", _infer_weak_points(profile.goal))
    preferences.setdefault("resource_preference", preferences.get("resource", "讲解文档"))
    return StudentProfileCreate(
        user_id=profile.user_id,
        profile_type=profile.profile_type,
        goal=profile.goal,
        level=profile.level,
        preferences=preferences,
        time_budget=profile.time_budget,
    )


def build_profile_from_dialogue(payload: StudentProfileDialogueCreate) -> StudentProfileCreate:
    text = " ".join(payload.dialogue.strip().split())
    preferences = {
        "style": _infer_learning_preference(text),
        "resource": _infer_resource_preference(text),
        "pace": _infer_pace(text),
        "dialogue_summary": text,
        "profile_origin": "user_dialogue",
    }
    profile = StudentProfileCreate(
        user_id=payload.user_id,
        profile_type=payload.profile_type or _infer_profile_type(text),
        goal=_infer_goal(text),
        level=_infer_level(text),
        preferences=preferences,
        time_budget=_infer_time_budget(text),
    )
    return normalize_profile_dimensions(profile)


def _infer_profile_type(text: str) -> ProfileType:
    lowered = text.lower()
    if _has_any(lowered, ["考试", "小测", "quiz", "exam", "冲刺", "复习"]):
        return ProfileType.exam_sprint
    if _has_any(lowered, ["代码", "编程", "刷题", "leetcode", "practice", "实现"]):
        return ProfileType.algorithm_practice
    return ProfileType.weak_foundation


def _infer_goal(text: str) -> str:
    if not text:
        return "构建数据结构学习画像并生成个性化学习路径。"
    if len(text) <= 140:
        return text
    return f"{text[:137]}..."


def _infer_level(text: str) -> str:
    lowered = text.lower()
    if _has_any(lowered, ["零基础", "基础薄弱", "看不懂", "beginner", "weak"]):
        return "beginner"
    if _has_any(lowered, ["会写", "刷题", "实现", "practice", "code"]):
        return "practice_oriented"
    if _has_any(lowered, ["复习", "考试", "小测", "intermediate", "exam"]):
        return "intermediate"
    return "beginner"


def _infer_time_budget(text: str) -> str:
    lowered = text.lower()
    for marker in ["每天", "每日", "每周", "一周", "周末"]:
        index = lowered.find(marker)
        if index >= 0:
            return text[index : min(len(text), index + 24)]
    if _has_any(lowered, ["1 hour", "one hour"]):
        return "每天 1 小时"
    if _has_any(lowered, ["2 hour", "two hour"]):
        return "每天 2 小时"
    return "每天 1 小时"


def _infer_learning_preference(text: str) -> str:
    lowered = text.lower()
    if _has_any(lowered, ["代码", "编程", "实现", "code"]):
        return "code_driven"
    if _has_any(lowered, ["例题", "样题", "worked"]):
        return "worked_examples"
    if _has_any(lowered, ["总结", "速记", "考点"]):
        return "summary_first"
    return "step_by_step"


def _infer_resource_preference(text: str) -> str:
    lowered = text.lower()
    if _has_any(lowered, ["思维导图", "脑图", "mind map"]):
        return "思维导图"
    if _has_any(lowered, ["代码", "编程", "实现", "code"]):
        return "代码实操案例"
    if _has_any(lowered, ["题", "quiz", "exam", "练习"]):
        return "练习题"
    return "讲解文档"


def _infer_pace(text: str) -> str:
    lowered = text.lower()
    if _has_any(lowered, ["冲刺", "快速", "一周", "fast"]):
        return "fast"
    if _has_any(lowered, ["慢", "细", "基础", "slow"]):
        return "slow"
    return "normal"


def _infer_weak_points(text: str) -> str:
    lowered = text.lower()
    weak_points = []
    for keyword, label in [
        ("复杂度", "复杂度分析"),
        ("链表", "链表"),
        ("栈", "栈/队列"),
        ("队列", "栈/队列"),
        ("树", "二叉树遍历"),
        ("bfs", "BFS/DFS"),
        ("dfs", "BFS/DFS"),
        ("图", "BFS/DFS"),
    ]:
        if keyword in lowered and label not in weak_points:
            weak_points.append(label)
    return "、".join(weak_points) if weak_points else "待通过测验进一步定位"


def _has_any(text: str, needles: list[str]) -> bool:
    return any(needle in text for needle in needles)
