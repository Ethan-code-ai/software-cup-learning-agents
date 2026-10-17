from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile, status

from app.domain.exceptions import ConflictError, GoalResolutionError, NotFoundError, ProtectedResourceError
from app.schemas import (
    ConceptGraphResponse,
    AgentRunResponse,
    AttemptSubmitRequest,
    DemoDataLoadResponse,
    DemoDataStatusResponse,
    DocumentChunkResponse,
    DocumentIngestionRequest,
    DocumentIngestionResponse,
    DocumentManagementResponse,
    DocumentReindexResponse,
    EvaluationResult,
    GeneratedResourceResponse,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    LearningFlowResponse,
    LearningPathCreate,
    LearningPathResponse,
    QuizGenerateRequest,
    QuizResponse,
    ResourceGenerateRequest,
    StudentProfileCreate,
    StudentProfileDialogueCreate,
    StudentProfileHistoryResponse,
    StudentProfileResponse,
    TutorAskRequest,
    TutorAskResponse,
    TaskResponse,
)
from app.agents.orchestrator import AgentOrchestrator
from app.services.agent_run_service import AgentRunService
from app.services.assessment_service import AssessmentService
from app.services.course_service import CourseService
from app.services.demo_data_service import DemoDataService
from app.services.document_management_service import DocumentManagementService
from app.services.document_ingestion_service import DocumentIngestionService
from app.services.knowledge_base_service import KnowledgeBaseService
from app.services.learning_path_service import LearningPathService
from app.services.profile_service import ProfileService
from app.services.profile_postprocessing_service import ProfilePostprocessingService
from app.services.profile_updater_service import ProfileUpdaterService
from app.services.resource_service import ResourceService
from app.services.tutor_service import TutorService
from app.services.task_service import TaskService

api_router = APIRouter()


@api_router.get("/demo-data/status", response_model=DemoDataStatusResponse)
def get_demo_data_status() -> DemoDataStatusResponse:
    return DemoDataService().get_status()


@api_router.post("/demo-data/load", response_model=DemoDataLoadResponse)
def load_demo_data() -> DemoDataLoadResponse:
    return DemoDataService().load_demo_data()


@api_router.post("/demo-data/reset-user-data", response_model=DemoDataLoadResponse)
def reset_demo_user_data() -> DemoDataLoadResponse:
    return DemoDataService().reset_user_data()


@api_router.get("/student-profiles", response_model=list[StudentProfileResponse])
def list_student_profiles() -> list[StudentProfileResponse]:
    return ProfileService().list_demo_profiles()


@api_router.post("/student-profiles", response_model=StudentProfileResponse)
def create_student_profile(payload: StudentProfileCreate) -> StudentProfileResponse:
    return ProfileService().create_profile(payload)


@api_router.post("/student-profiles/from-dialogue", response_model=StudentProfileResponse)
def create_student_profile_from_dialogue(payload: StudentProfileDialogueCreate) -> StudentProfileResponse:
    return ProfileService().create_profile_from_dialogue(payload)


@api_router.get("/student-profiles/{profile_id}", response_model=StudentProfileResponse)
def get_student_profile(profile_id: int) -> StudentProfileResponse:
    try:
        return ProfileService().get_profile(profile_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@api_router.delete("/student-profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_student_profile(profile_id: int) -> None:
    try:
        ProfileService().delete_profile(profile_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ProtectedResourceError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@api_router.post("/student-profiles/{profile_id}/update-from-trace", response_model=StudentProfileResponse)
def update_student_profile_from_trace(profile_id: int) -> StudentProfileResponse:
    try:
        return ProfileUpdaterService().update_from_trace(profile_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@api_router.get("/courses/{course_id}/graph", response_model=ConceptGraphResponse)
def get_course_graph(course_id: int) -> ConceptGraphResponse:
    try:
        return CourseService().get_concept_graph(course_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@api_router.post("/courses/{course_id}/documents", response_model=DocumentIngestionResponse)
def ingest_course_document(course_id: int, payload: DocumentIngestionRequest) -> DocumentIngestionResponse:
    try:
        return DocumentIngestionService().ingest(course_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@api_router.post("/courses/{course_id}/documents/upload", response_model=DocumentIngestionResponse)
async def upload_course_document(
    course_id: int,
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    visibility: str = Form(default="course"),
    owner_user_id: int | None = Form(default=None),
) -> DocumentIngestionResponse:
    try:
        content = await file.read()
        return DocumentIngestionService().ingest_upload(
            course_id,
            filename=file.filename or "uploaded-document",
            content_type=file.content_type,
            content=content,
            title=title,
            visibility=visibility,
            owner_user_id=owner_user_id,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@api_router.get("/student-profiles/{profile_id}/history", response_model=list[StudentProfileHistoryResponse])
def list_student_profile_history(profile_id: int, limit: int = 20) -> list[StudentProfileHistoryResponse]:
    if limit < 1 or limit > 100:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="limit must be between 1 and 100")
    try:
        return ProfileService().list_profile_history(profile_id, limit)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@api_router.get("/courses/{course_id}/documents", response_model=list[DocumentManagementResponse])
def list_course_documents(course_id: int) -> list[DocumentManagementResponse]:
    try:
        return DocumentManagementService().list_course_documents(course_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@api_router.get("/documents/{document_id}", response_model=DocumentManagementResponse)
def get_document(document_id: int) -> DocumentManagementResponse:
    try:
        return DocumentManagementService().get_document(document_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@api_router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: int) -> None:
    try:
        DocumentManagementService().delete_document(document_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ProtectedResourceError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@api_router.post("/documents/{document_id}/reindex", response_model=DocumentReindexResponse)
def reindex_document(document_id: int) -> DocumentReindexResponse:
    try:
        return DocumentManagementService().reindex_document(document_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@api_router.get("/documents/{document_id}/chunks", response_model=list[DocumentChunkResponse])
def list_document_chunks(document_id: int) -> list[DocumentChunkResponse]:
    try:
        return DocumentIngestionService().list_chunks(document_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@api_router.post("/knowledge/search", response_model=KnowledgeSearchResponse)
def search_knowledge(payload: KnowledgeSearchRequest) -> KnowledgeSearchResponse:
    results = KnowledgeBaseService().search(payload.course_id, payload.query, payload.top_k, payload.owner_user_id)
    return KnowledgeSearchResponse(results=results)


@api_router.post("/learning-paths", response_model=LearningFlowResponse)
def create_learning_path(payload: LearningPathCreate) -> LearningFlowResponse:
    try:
        result = AgentOrchestrator().run_learning_flow(
            payload.student_profile_id,
            payload.course_id,
            payload.goal,
        )
        return LearningFlowResponse(
            learning_path=LearningPathService().get_path(result.learning_path_id),
            agent_run=AgentRunService().get_run(result.agent_run_id),
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except GoalResolutionError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@api_router.get("/learning-paths/{path_id}", response_model=LearningPathResponse)
def get_learning_path(path_id: int) -> LearningPathResponse:
    try:
        return LearningPathService().get_path(path_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@api_router.post("/learning-path-items/{item_id}/complete", response_model=LearningPathResponse)
def complete_learning_path_item(item_id: int) -> LearningPathResponse:
    try:
        return LearningPathService().complete_item(item_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@api_router.get("/agent-runs/{run_id}", response_model=AgentRunResponse)
def get_agent_run(run_id: int) -> AgentRunResponse:
    try:
        return AgentRunService().get_run(run_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@api_router.post("/resources/generate", response_model=GeneratedResourceResponse)
def generate_resource(payload: ResourceGenerateRequest, background_tasks: BackgroundTasks) -> GeneratedResourceResponse:
    try:
        response = ResourceService().generate_resource(payload.path_item_id, payload.resource_type)
        if response.postprocessing_task_id is not None:
            background_tasks.add_task(
                ProfilePostprocessingService().process,
                response.postprocessing_task_id,
            )
        return response
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@api_router.post("/tutor/ask", response_model=TutorAskResponse)
def ask_tutor(payload: TutorAskRequest, background_tasks: BackgroundTasks) -> TutorAskResponse:
    try:
        response = TutorService().ask(payload.student_profile_id, payload.course_id, payload.question)
        if response.postprocessing_task_id is not None:
            background_tasks.add_task(
                ProfilePostprocessingService().process,
                response.postprocessing_task_id,
            )
        return response
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@api_router.post("/quizzes/generate", response_model=QuizResponse)
def generate_quiz(payload: QuizGenerateRequest) -> QuizResponse:
    try:
        return AssessmentService().generate_quiz(payload.student_profile_id, payload.concept_id, payload.difficulty)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@api_router.post("/quizzes/{quiz_id}/attempts", response_model=EvaluationResult)
def submit_quiz_attempt(
    quiz_id: int,
    payload: AttemptSubmitRequest,
    background_tasks: BackgroundTasks,
) -> EvaluationResult:
    try:
        service = AssessmentService()
        result = service.submit_attempt(
            quiz_id,
            payload.student_profile_id,
            payload.answers,
            learning_path_id=payload.learning_path_id,
            run_postprocessing=payload.run_postprocessing,
        )
        if result.postprocessing_task_id is not None:
            background_tasks.add_task(service.process_attempt_postprocessing, result.postprocessing_task_id)
        return result
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@api_router.get("/tasks/{task_id}", response_model=TaskResponse)
def get_task(task_id: int) -> TaskResponse:
    try:
        return TaskService().get_task(task_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
