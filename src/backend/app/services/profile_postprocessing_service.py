import json

from app.services.profile_updater_service import ProfileUpdaterService
from app.services.task_service import TaskService


class ProfilePostprocessingService:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url

    def schedule(self, profile_id: int, trigger_type: str, event_key: str):
        result_ref = json.dumps(
            {
                "profile_id": profile_id,
                "trigger_type": trigger_type,
                "event_key": event_key,
            },
            separators=(",", ":"),
        )
        return TaskService(database_url=self.database_url).create_task(
            "profile_trace_postprocessing",
            result_ref=result_ref,
        )

    def process(self, task_id: int) -> None:
        task_service = TaskService(database_url=self.database_url)
        task = task_service.get_task(task_id)
        if task.status != "pending":
            return
        task_service.mark_running(task_id)
        try:
            payload = json.loads(task.result_ref or "{}")
            profile_id = int(payload["profile_id"])
            trigger_type = str(payload["trigger_type"])
            event_key = str(payload["event_key"])
            ProfileUpdaterService(database_url=self.database_url).update_from_trace(
                profile_id,
                trigger_type=trigger_type,
                event_key=event_key,
            )
            task_service.mark_completed(task_id)
        except Exception as exc:
            task_service.mark_failed(task_id, exc)
