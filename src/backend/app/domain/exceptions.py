class DomainError(Exception):
    """Base class for domain-layer errors."""


class NotFoundError(DomainError):
    def __init__(self, resource: str, resource_id: int) -> None:
        self.resource = resource
        self.resource_id = resource_id
        super().__init__(f"{resource} {resource_id} not found.")


class ProtectedResourceError(DomainError):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class ConflictError(DomainError):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class GoalResolutionError(DomainError):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            message
            or "无法从当前描述中确定学习目标，请补充具体知识点、学习目的或时间要求。"
        )
