import json
import re
from dataclasses import replace
from typing import Any

from sqlalchemy import select

from app.agents.critic_agents import RuleBasedCriticAgent
from app.agents.evaluator_factory import build_evaluator_agent
from app.agents.quiz_agents import QuizContext
from app.agents.quiz_factory import build_quiz_agent
from app.agents.router_agent import RuleBasedRouterAgent
from app.agents.rule_based_agents import EvaluatorAgentResult, RuleBasedQuizAgent
from app.db.session import session_scope
from app.domain.exceptions import NotFoundError
from app.models import (
    Attempt,
    Concept,
    LearningPath,
    MasteryRecord,
    Quiz,
    QuizItem,
    QuizItemGenerationMetadata,
    StudentProfile,
)
from app.schemas import EvaluationResult, QuizItemResponse, QuizResponse
from app.services.agent_run_service import AgentRunService
from app.services.agent_execution_metadata import build_execution_metadata
from app.services.demo_data_service import DemoDataService
from app.services.content_safety_service import ContentSafetyService
from app.services.knowledge_base_service import KnowledgeBaseService
from app.services.learning_path_service import LearningPathService
from app.services.profile_updater_service import ProfileUpdaterService
from app.services.task_service import TaskService


class AssessmentService:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url
        self.quiz_agent = build_quiz_agent()
        self.evaluator_agent = build_evaluator_agent()
        self.router_agent = RuleBasedRouterAgent()
        self.critic_agent = RuleBasedCriticAgent()

    def generate_quiz(self, profile_id: int, concept_id: int, difficulty: str) -> QuizResponse:
        DemoDataService(database_url=self.database_url).get_status()

        with session_scope(self.database_url) as session:
            profile = session.get(StudentProfile, profile_id)
            concept = session.get(Concept, concept_id)
            if profile is None:
                raise NotFoundError("Student profile", profile_id)
            if concept is None:
                raise NotFoundError("Concept", concept_id)

            profile_id_value = profile.id
            concept_id_value = concept.id
            concept_name = concept.name
            concept_slug = concept.slug
            course_id = concept.course_id
            owner_user_id = profile.user_id
            profile_preferences = profile.preferences if isinstance(profile.preferences, dict) else {}
            profile_preferences = {
                **profile_preferences,
                "foundation_level": profile.level,
                "learning_goal": profile.goal,
                "available_time": profile.time_budget,
                "profile_type": profile.profile_type,
            }
            mastery = session.scalar(
                select(MasteryRecord)
                .where(
                    MasteryRecord.student_profile_id == profile.id,
                    MasteryRecord.concept_id == concept.id,
                )
                .order_by(MasteryRecord.id.desc())
            )
            recent_attempts = session.scalars(
                select(Attempt)
                .join(Quiz, Attempt.quiz_id == Quiz.id)
                .where(
                    Attempt.student_profile_id == profile.id,
                    Quiz.concept_id == concept.id,
                    Attempt.score < 1.0,
                )
                .order_by(Attempt.id.desc())
                .limit(3)
            ).all()
            quiz_context = QuizContext(
                profile_preferences=profile_preferences,
                mastery_score=mastery.mastery_score if mastery is not None else None,
                recent_errors=[
                    f"score={attempt.score:.2f}; feedback={(attempt.feedback or '无反馈')[:160]}"
                    for attempt in recent_attempts
                ],
            )

        route = self.router_agent.route_quiz_generation(difficulty, concept_name, profile_preferences)
        effective_difficulty = str(route.constraints.get("effective_difficulty") or difficulty)
        run_service = AgentRunService(database_url=self.database_url)
        run = run_service.start_run(
            "quiz_generation",
            profile_id_value,
            course_id,
            input_summary=route.to_log_summary(),
        )
        run_service.record_step(
            run.id,
            "router",
            input_summary=f"requested_difficulty={difficulty}; concept={concept_name}",
            output_summary=route.to_log_summary(),
            decision_basis=f"Router Agent dispatches quiz task with constraints: {route.constraints}",
            status="completed",
        )
        retrieved_chunks = KnowledgeBaseService(database_url=self.database_url).search(
            course_id,
            concept_slug,
            top_k=3,
            owner_user_id=owner_user_id,
        )
        retrieval_safety = ContentSafetyService().filter_retrieved_chunks(retrieved_chunks)
        chunks = retrieval_safety.safe_chunks
        run_service.record_step(
            run.id,
            "retriever",
            input_summary=f"query={concept_slug}; top_k=3",
            output_summary=(
                f"Retriever Agent returned {len(retrieved_chunks)} chunks; "
                f"{len(chunks)} passed deterministic safety filtering for Quiz Agent."
            ),
            decision_basis="Only Retriever Agent can call KnowledgeBaseService.search for quiz grounding.",
            status="completed",
            execution_metadata=build_execution_metadata(
                source_refs=[chunk.source_ref for chunk in chunks if chunk.source_ref]
            ),
        )
        if retrieval_safety.blocked_source_refs:
            run_service.record_step(
                run.id,
                "evaluator",
                input_summary="Review retrieved chunks as untrusted content.",
                output_summary=f"安全规则隔离了 {len(retrieval_safety.blocked_source_refs)} 个 RAG 污染片段。",
                decision_basis=(
                    "unsafe untrusted content detected in retrieved source refs: "
                    + ",".join(retrieval_safety.blocked_source_refs)
                ),
                status="completed",
                execution_metadata=build_execution_metadata(source_refs=retrieval_safety.blocked_source_refs),
            )
        if not chunks:
            with session_scope(self.database_url) as session:
                quiz = Quiz(
                    concept_id=concept_id_value,
                    student_profile_id=profile_id_value,
                    difficulty=effective_difficulty,
                    status="failed",
                )
                session.add(quiz)
                session.flush()
                response = self._to_quiz_response(quiz, [], [])
            message = "课程资料不足或检索证据未通过安全校验，未生成测验题目。"
            run_service.record_step(
                run.id,
                "quiz",
                input_summary=f"concept={concept_name}; difficulty={effective_difficulty}",
                output_summary=message,
                decision_basis="无安全可用的 Retriever chunk 时拒绝生成题目，避免无依据编题。",
                status="completed",
            )
            run_service.complete_run(run.id, message)
            response.agent_run_id = run.id
            response.safety_status = "degraded"
            response.safety_message = message
            return response
        result = self.quiz_agent.generate(concept_name, effective_difficulty, chunks, quiz_context)
        run_service.record_step(
            run.id,
            "quiz",
            result.input_summary,
            result.output_summary,
            result.decision_basis,
            "completed",
            duration_ms=result.duration_ms,
            execution_metadata=build_execution_metadata(result),
        )
        available_source_refs = {str(chunk.source_ref) for chunk in chunks if chunk.source_ref}
        critic = self.critic_agent.review_quiz(
            result,
            effective_difficulty,
            profile_preferences,
            available_source_refs,
        )
        run_service.record_step(
            run.id,
            "evaluator",
            input_summary=f"review quiz difficulty={effective_difficulty}",
            output_summary=critic.output_summary,
            decision_basis=critic.decision_basis,
            status="completed" if critic.approved else "failed",
        )
        if not critic.approved:
            effective_difficulty = "easy"
            result = self.quiz_agent.generate(concept_name, effective_difficulty, chunks, quiz_context)
            run_service.record_step(
                run.id,
                "quiz",
                result.input_summary,
                f"Quiz Agent regenerated after Critic feedback. {result.output_summary}",
                f"Revision instruction: {critic.revision_instruction}. {result.decision_basis}",
                "completed",
                duration_ms=result.duration_ms,
                execution_metadata=build_execution_metadata(result),
            )
            second_critic = self.critic_agent.review_quiz(
                result,
                effective_difficulty,
                profile_preferences,
                available_source_refs,
            )
            run_service.record_step(
                run.id,
                "evaluator",
                input_summary="review regenerated quiz",
                output_summary=second_critic.output_summary,
                decision_basis=second_critic.decision_basis,
                status="completed" if second_critic.approved else "failed",
            )
            if not second_critic.approved:
                rejected_result = result
                fallback_reason = f"Critic rejected regenerated quiz: {second_critic.output_summary}"
                result = replace(
                    RuleBasedQuizAgent().generate(concept_name, effective_difficulty, chunks, quiz_context),
                    execution_mode="rule_based_critic_fallback",
                    provider=rejected_result.provider,
                    model=rejected_result.model,
                    fallback_used=True,
                    fallback_reason=fallback_reason,
                    duration_ms=rejected_result.duration_ms,
                    output_summary="Critic 连续拒绝 LLM 题目，已使用 rule-based Quiz Agent 生成安全题目。",
                    decision_basis=(
                        f"execution_mode=rule_based_critic_fallback; provider={rejected_result.provider}; "
                        f"model={rejected_result.model or 'none'}; fallback_used=true; "
                        f"fallback_reason={fallback_reason}; source_refs="
                        f"{','.join(sorted(available_source_refs))}"
                    ),
                )
                run_service.record_step(
                    run.id,
                    "quiz",
                    result.input_summary,
                    result.output_summary,
                    result.decision_basis,
                    "completed",
                    duration_ms=result.duration_ms,
                    execution_metadata=build_execution_metadata(result),
                )
                final_critic = self.critic_agent.review_quiz(
                    result,
                    effective_difficulty,
                    profile_preferences,
                    available_source_refs,
                )
                run_service.record_step(
                    run.id,
                    "evaluator",
                    input_summary="review rule-based safety fallback quiz",
                    output_summary=final_critic.output_summary,
                    decision_basis=final_critic.decision_basis,
                    status="completed" if final_critic.approved else "failed",
                )
                if not final_critic.approved:
                    raise ValueError(f"Quiz safety fallback failed Critic review: {final_critic.output_summary}")

        with session_scope(self.database_url) as session:
            quiz = Quiz(
                concept_id=concept_id_value,
                student_profile_id=profile_id_value,
                difficulty=effective_difficulty,
                status="completed",
            )
            session.add(quiz)
            session.flush()
            item = QuizItem(
                quiz_id=quiz.id,
                question=result.question,
                answer=result.answer,
                explanation=result.explanation,
                difficulty=effective_difficulty,
                concept_tags=result.concept_tags,
            )
            session.add(item)
            session.flush()
            metadata = QuizItemGenerationMetadata(
                quiz_item_id=item.id,
                question_type=result.question_type,
                options=result.options,
                source_refs=result.source_refs,
                execution_mode=result.execution_mode,
                provider=result.provider,
                model=result.model,
                fallback_used=result.fallback_used,
                fallback_reason=result.fallback_reason,
                duration_ms=result.duration_ms,
            )
            session.add(metadata)
            session.flush()
            response = self._to_quiz_response(quiz, [item], [metadata])

        run_service.complete_run(run.id, f"Multi-agent quiz flow generated quiz {response.id} for concept {concept_id_value}.")
        response.agent_run_id = run.id
        return response

    def submit_attempt(
        self,
        quiz_id: int,
        profile_id: int,
        answers: dict[str, Any],
        learning_path_id: int | None = None,
        run_postprocessing: bool = True,
    ) -> EvaluationResult:
        DemoDataService(database_url=self.database_url).get_status()

        with session_scope(self.database_url) as session:
            quiz = session.get(Quiz, quiz_id)
            profile = session.get(StudentProfile, profile_id)
            if quiz is None:
                raise NotFoundError("Quiz", quiz_id)
            if profile is None:
                raise NotFoundError("Student profile", profile_id)
            item = session.scalar(select(QuizItem).where(QuizItem.quiz_id == quiz.id).order_by(QuizItem.id))
            if item is None:
                raise NotFoundError("Quiz item", quiz_id)
            concept = session.get(Concept, quiz.concept_id)
            if concept is None:
                raise NotFoundError("Concept", quiz.concept_id)

            quiz_id_value = quiz.id
            profile_id_value = profile.id
            expected_answer = item.answer
            concept_id_value = concept.id
            course_id = concept.course_id
            path_query = (
                select(LearningPath)
                .where(
                    LearningPath.student_profile_id == profile.id,
                    LearningPath.course_id == course_id,
                    LearningPath.status == "active",
                )
                .order_by(LearningPath.id.desc())
            )
            if learning_path_id is not None:
                path_query = path_query.where(LearningPath.id == learning_path_id)
            selected_path = session.scalar(path_query.limit(1))
            if learning_path_id is not None and selected_path is None:
                raise NotFoundError("Active learning path", learning_path_id)
            selected_path_id = selected_path.id if selected_path is not None else None
            metadata = session.scalar(
                select(QuizItemGenerationMetadata).where(QuizItemGenerationMetadata.quiz_item_id == item.id)
            )

        if metadata is not None and metadata.question_type in {"multiple_choice", "fill_blank"}:
            result = self._evaluate_objective_answer(
                expected_answer,
                answers,
                concept_id_value,
                metadata.question_type,
                metadata.options,
            )
        else:
            result = self.evaluator_agent.evaluate(expected_answer, answers, concept_id_value)

        with session_scope(self.database_url) as session:
            attempt = Attempt(
                quiz_id=quiz_id_value,
                student_profile_id=profile_id_value,
                answers=answers,
                score=result.score,
                feedback=result.feedback,
            )
            session.add(attempt)
            session.flush()
            attempt_id = attempt.id
            for update in result.mastery_updates:
                session.add(
                    MasteryRecord(
                        student_profile_id=profile_id_value,
                        concept_id=update["concept_id"],
                        mastery_score=update["mastery_score"],
                        evidence=update["evidence"],
                    )
                )

        run_service = AgentRunService(database_url=self.database_url)
        run = run_service.start_run(
            "attempt_evaluation",
            profile_id_value,
            course_id,
            input_summary=result.input_summary,
        )
        run_service.record_step(
            run.id,
            "evaluator",
            result.input_summary,
            result.output_summary,
            result.decision_basis,
            "completed",
            execution_metadata=build_execution_metadata(result),
        )
        run_service.complete_run(run.id, f"Evaluator Agent evaluated attempt {attempt_id}.")
        postprocessing_task = None
        if run_postprocessing:
            result_ref = json.dumps(
                {"attempt_id": attempt_id, "learning_path_id": selected_path_id},
                separators=(",", ":"),
            )
            postprocessing_task = TaskService(database_url=self.database_url).create_task(
                "quiz_postprocessing",
                result_ref=result_ref,
            )
        return EvaluationResult(
            attempt_id=attempt_id,
            score=result.score,
            feedback=result.feedback,
            mastery_updates=result.mastery_updates,
            agent_run_id=run.id,
            postprocessing_task_id=postprocessing_task.id if postprocessing_task is not None else None,
            postprocessing_status=postprocessing_task.status if postprocessing_task is not None else "not_requested",
        )

    def process_attempt_postprocessing(self, task_id: int) -> None:
        task_service = TaskService(database_url=self.database_url)
        task = task_service.get_task(task_id)
        if task.status != "pending":
            return
        task_service.mark_running(task_id)
        try:
            payload = json.loads(task.result_ref or "{}")
            attempt_id = int(payload["attempt_id"])
            path_id = payload.get("learning_path_id")
            path_id = int(path_id) if path_id is not None else None
            with session_scope(self.database_url) as session:
                attempt = session.get(Attempt, attempt_id)
                if attempt is None:
                    raise NotFoundError("Attempt", attempt_id)
                quiz = session.get(Quiz, attempt.quiz_id)
                if quiz is None:
                    raise NotFoundError("Quiz", attempt.quiz_id)
                concept = session.get(Concept, quiz.concept_id)
                if concept is None:
                    raise NotFoundError("Concept", quiz.concept_id)
                profile_id = attempt.student_profile_id
                course_id = concept.course_id

            ProfileUpdaterService(database_url=self.database_url).update_from_trace(
                profile_id,
                trigger_type="quiz",
                event_key=f"quiz:{attempt_id}",
            )
            if path_id is not None:
                LearningPathService(database_url=self.database_url).refresh_active_paths(
                    profile_id,
                    course_id,
                    trigger=f"quiz:{attempt_id}",
                    path_id=path_id,
                )
            task_service.mark_completed(task_id)
        except Exception as exc:
            task_service.mark_failed(task_id, exc)

    def _to_quiz_response(
        self,
        quiz: Quiz,
        items: list[QuizItem],
        metadata_rows: list[QuizItemGenerationMetadata] | None = None,
        agent_run_id: int | None = None,
    ) -> QuizResponse:
        by_item = {row.quiz_item_id: row for row in metadata_rows or []}
        first_metadata = next(iter(by_item.values()), None)
        return QuizResponse(
            id=quiz.id,
            student_profile_id=quiz.student_profile_id,
            concept_id=quiz.concept_id,
            difficulty=quiz.difficulty,
            status=quiz.status,
            items=[
                QuizItemResponse(
                    id=item.id,
                    question=item.question,
                    answer=item.answer,
                    explanation=item.explanation,
                    difficulty=item.difficulty,
                    concept_tags=item.concept_tags,
                    question_type=by_item[item.id].question_type if item.id in by_item else "short_answer",
                    options=by_item[item.id].options if item.id in by_item else [],
                    source_refs=by_item[item.id].source_refs if item.id in by_item else [],
                )
                for item in items
            ],
            created_at=quiz.created_at,
            agent_run_id=agent_run_id,
            execution_mode=first_metadata.execution_mode if first_metadata else "rule_based",
            provider=first_metadata.provider if first_metadata else "rule_based",
            model=first_metadata.model if first_metadata else "",
            fallback_used=first_metadata.fallback_used if first_metadata else False,
            fallback_reason=first_metadata.fallback_reason if first_metadata else None,
            quiz_duration_ms=first_metadata.duration_ms if first_metadata else 0,
        )

    @staticmethod
    def _evaluate_objective_answer(
        expected_answer: str,
        answers: dict[str, Any],
        concept_id: int,
        question_type: str,
        options: list[str],
    ) -> EvaluatorAgentResult:
        submitted = " ".join(str(value) for value in answers.values()).strip()
        expected = _normalize_objective_answer(expected_answer, question_type, options)
        actual = _normalize_objective_answer(submitted, question_type, options)
        score = 1.0 if actual and actual == expected else 0.0
        feedback = "客观题答案正确，已按确定性规则计分。" if score == 1.0 else "客观题答案不正确，请结合解析复习后重试。"
        return EvaluatorAgentResult(
            score=score,
            feedback=feedback,
            mastery_updates=[
                {
                    "concept_id": concept_id,
                    "mastery_score": score,
                    "evidence": {
                        "analysis_method": "deterministic",
                        "question_type": question_type,
                        "answer_matched": score == 1.0,
                    },
                }
            ],
            input_summary=f"使用确定性规则评价 concept_id={concept_id} 的 {question_type} 客观题。",
            output_summary=f"Objective Evaluator 返回确定性评分 {score:.2f}。",
            decision_basis=(
                f"evaluation_mode=deterministic; question_type={question_type}; "
                "objective answers are normalized and compared exactly; no LLM call is used."
            ),
        )


def _normalize_objective_answer(value: str, question_type: str, options: list[str]) -> str:
    normalized = "".join(value.strip().lower().split())
    if question_type != "multiple_choice":
        return normalized.strip("。．.，,；;：:")
    label_match = re.match(r"^([a-h])(?:[\.、:：\s]|$)", value.strip().lower())
    if label_match:
        return label_match.group(1)
    for option in options:
        if normalized == "".join(option.strip().lower().split()):
            return option.strip()[:1].lower()
    return normalized
