from app.db.session import session_scope
from app.domain.exceptions import NotFoundError
from app.models import Task
from app.schemas import TaskResponse
from app.services.agent_execution_metadata import sanitize_trace_text


class TaskService:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url

    def create_task(self, task_type: str, result_ref: str | None = None) -> TaskResponse:
        with session_scope(self.database_url) as session:
            task = Task(task_type=task_type, status="pending", result_ref=result_ref)
            session.add(task)
            session.flush()
            return TaskResponse.model_validate(task)

    def get_task(self, task_id: int) -> TaskResponse:
        with session_scope(self.database_url) as session:
            task = session.get(Task, task_id)
            if task is None:
                raise NotFoundError("Task", task_id)
            return TaskResponse.model_validate(task)

    def mark_running(self, task_id: int) -> TaskResponse:
        return self._update(task_id, status="running", error=None)

    def mark_completed(self, task_id: int) -> TaskResponse:
        return self._update(task_id, status="completed", error=None)

    def mark_failed(self, task_id: int, error: BaseException) -> TaskResponse:
        safe_error = sanitize_trace_text(f"{type(error).__name__}: {error}", 1000)
        return self._update(task_id, status="failed", error=safe_error)

    def _update(self, task_id: int, *, status: str, error: str | None) -> TaskResponse:
        with session_scope(self.database_url) as session:
            task = session.get(Task, task_id)
            if task is None:
                raise NotFoundError("Task", task_id)
            task.status = status
            task.error = error
            session.flush()
            return TaskResponse.model_validate(task)
