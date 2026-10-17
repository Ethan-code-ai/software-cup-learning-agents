from datetime import datetime

from sqlalchemy import func, select

from app.db.session import session_scope
from app.db.schema_compat import ensure_agent_run_step_columns
from app.domain.exceptions import NotFoundError
from app.models import AgentRun, AgentRunStep
from app.schemas import AgentRunResponse, AgentRunStepResponse
from app.services.agent_execution_metadata import sanitize_execution_metadata, sanitize_trace_text


class AgentRunService:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url

    def start_run(
        self,
        run_type: str,
        profile_id: int,
        course_id: int,
        input_summary: str | None = None,
    ) -> AgentRunResponse:
        ensure_agent_run_step_columns(self.database_url)
        with session_scope(self.database_url) as session:
            run = AgentRun(
                run_type=run_type,
                student_profile_id=profile_id,
                course_id=course_id,
                status="running",
                input_summary=sanitize_trace_text(input_summary, 2000),
            )
            session.add(run)
            session.flush()
            return self._to_run_response(run, [])

    def record_step(
        self,
        run_id: int,
        agent_type: str,
        input_summary: str,
        output_summary: str,
        decision_basis: str,
        status: str,
        duration_ms: int | None = None,
        error: str | None = None,
        execution_metadata: dict | None = None,
    ) -> AgentRunStepResponse:
        metadata = sanitize_execution_metadata(execution_metadata)
        resolved_duration_ms = duration_ms if duration_ms is not None else metadata.duration_ms
        if metadata.duration_ms != resolved_duration_ms:
            metadata = metadata.model_copy(update={"duration_ms": max(0, int(resolved_duration_ms or 0))})
        with session_scope(self.database_url) as session:
            run = session.get(AgentRun, run_id)
            if run is None:
                raise NotFoundError("Agent run", run_id)
            next_order = int(
                session.scalar(
                    select(func.count()).select_from(AgentRunStep).where(AgentRunStep.agent_run_id == run_id)
                )
                or 0
            ) + 1
            step = AgentRunStep(
                agent_run_id=run_id,
                agent_type=agent_type,
                step_order=next_order,
                status=status,
                input_summary=sanitize_trace_text(input_summary, 2000),
                output_summary=sanitize_trace_text(output_summary, 2000),
                decision_basis=sanitize_trace_text(decision_basis, 2000),
                duration_ms=resolved_duration_ms,
                error=sanitize_trace_text(error, 1000) or None,
                execution_metadata=metadata.model_dump(),
            )
            session.add(step)
            session.flush()
            return AgentRunStepResponse.model_validate(step)

    def complete_run(self, run_id: int, final_summary: str) -> AgentRunResponse:
        with session_scope(self.database_url) as session:
            run = session.get(AgentRun, run_id)
            if run is None:
                raise NotFoundError("Agent run", run_id)
            run.status = "completed"
            safe_summary = sanitize_trace_text(final_summary, 2000)
            run.output_summary = safe_summary
            run.final_summary = safe_summary
            run.completed_at = datetime.utcnow()
            session.flush()
            steps = self._load_steps(session, run_id)
            return self._to_run_response(run, steps)

    def fail_run(self, run_id: int, error: str) -> AgentRunResponse:
        with session_scope(self.database_url) as session:
            run = session.get(AgentRun, run_id)
            if run is None:
                raise NotFoundError("Agent run", run_id)
            safe_error = sanitize_trace_text(error, 1000)
            run.status = "failed"
            run.error = safe_error
            run.final_summary = safe_error
            run.completed_at = datetime.utcnow()
            session.flush()
            return self._to_run_response(run, self._load_steps(session, run_id))

    def get_run(self, run_id: int) -> AgentRunResponse:
        with session_scope(self.database_url) as session:
            run = session.get(AgentRun, run_id)
            if run is None:
                raise NotFoundError("Agent run", run_id)
            return self._to_run_response(run, self._load_steps(session, run_id))

    def _load_steps(self, session, run_id: int) -> list[AgentRunStep]:
        return session.scalars(
            select(AgentRunStep).where(AgentRunStep.agent_run_id == run_id).order_by(AgentRunStep.step_order)
        ).all()

    def _to_run_response(self, run: AgentRun, steps: list[AgentRunStep]) -> AgentRunResponse:
        return AgentRunResponse(
            id=run.id,
            run_type=run.run_type,
            student_profile_id=run.student_profile_id,
            course_id=run.course_id,
            status=run.status,
            input_summary=run.input_summary,
            output_summary=run.output_summary,
            final_summary=run.final_summary,
            duration_ms=run.duration_ms,
            error=run.error,
            created_at=run.created_at,
            completed_at=run.completed_at,
            steps=[AgentRunStepResponse.model_validate(step) for step in steps],
        )
