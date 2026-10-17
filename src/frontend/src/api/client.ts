import type {
  AgentRun,
  ConceptGraph,
  DemoDataStatus,
  DocumentIngestionRequest,
  DocumentIngestionResponse,
  DocumentReindexResponse,
  EvaluationResult,
  GeneratedResource,
  KnowledgeSearchResponse,
  LearningFlow,
  ManagedDocument,
  Quiz,
  StudentProfileDialogueCreate,
  StudentProfile,
  StudentProfileHistory,
  Task,
  TutorAnswer
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const isFormData = init?.body instanceof FormData;
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      ...(isFormData ? {} : { "Content-Type": "application/json" }),
      ...(init?.headers ?? {})
    },
    ...init
  });

    if (!response.ok) {
      const text = await response.text();
      let message = text;
      try {
        const payload = JSON.parse(text) as { detail?: string };
        message = payload.detail || text;
      } catch {
        // Keep non-JSON server errors unchanged.
      }
      throw new Error(message || `请求失败（HTTP ${response.status}）`);
  }

  const text = await response.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export const api = {
  getDemoStatus: () => request<DemoDataStatus>("/demo-data/status"),
  loadDemoData: () => request<{ demo_data: DemoDataStatus }>("/demo-data/load", { method: "POST" }),
  resetDemoUserData: () => request<{ demo_data: DemoDataStatus }>("/demo-data/reset-user-data", { method: "POST" }),
  listProfiles: () => request<StudentProfile[]>("/student-profiles"),
  getProfile: (profileId: number) => request<StudentProfile>(`/student-profiles/${profileId}`),
  getProfileHistory: (profileId: number, limit = 20) =>
    request<StudentProfileHistory[]>(`/student-profiles/${profileId}/history?limit=${limit}`),
  createProfileFromDialogue: (payload: StudentProfileDialogueCreate) =>
    request<StudentProfile>("/student-profiles/from-dialogue", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  updateProfileFromTrace: (profileId: number) =>
    request<StudentProfile>(`/student-profiles/${profileId}/update-from-trace`, { method: "POST" }),
  deleteProfile: async (profileId: number) => {
    await request<void>(`/student-profiles/${profileId}`, { method: "DELETE" });
  },
  getCourseGraph: (courseId: number) => request<ConceptGraph>(`/courses/${courseId}/graph`),
  ingestCourseDocument: (courseId: number, payload: DocumentIngestionRequest) =>
    request<DocumentIngestionResponse>(`/courses/${courseId}/documents`, {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  uploadCourseDocument: (
    courseId: number,
    file: File,
    payload: { title?: string; visibility?: string; ownerUserId?: number | null } = {}
  ) => {
    const formData = new FormData();
    formData.append("file", file);
    if (payload.title) formData.append("title", payload.title);
    if (payload.visibility) formData.append("visibility", payload.visibility);
    if (payload.ownerUserId !== undefined && payload.ownerUserId !== null) {
      formData.append("owner_user_id", String(payload.ownerUserId));
    }
    return request<DocumentIngestionResponse>(`/courses/${courseId}/documents/upload`, {
      method: "POST",
      body: formData
    });
  },
  listCourseDocuments: (courseId: number) => request<ManagedDocument[]>(`/courses/${courseId}/documents`),
  deleteDocument: async (documentId: number) => {
    await request<void>(`/documents/${documentId}`, { method: "DELETE" });
  },
  reindexDocument: (documentId: number) =>
    request<DocumentReindexResponse>(`/documents/${documentId}/reindex`, { method: "POST" }),
  searchKnowledge: (courseId: number, query: string, topK = 3) =>
    request<KnowledgeSearchResponse>("/knowledge/search", {
      method: "POST",
      body: JSON.stringify({ course_id: courseId, query, top_k: topK })
    }),
  createLearningPath: (studentProfileId: number, courseId: number, goal: string) =>
    request<LearningFlow>("/learning-paths", {
      method: "POST",
      body: JSON.stringify({ student_profile_id: studentProfileId, course_id: courseId, goal })
    }),
  getLearningPath: (pathId: number) => request<import("./types").LearningPath>(`/learning-paths/${pathId}`),
  completePathItem: (itemId: number) =>
    request<import("./types").LearningPath>(`/learning-path-items/${itemId}/complete`, { method: "POST" }),
  generateResource: (pathItemId: number, resourceType: string) =>
    request<GeneratedResource>("/resources/generate", {
      method: "POST",
      body: JSON.stringify({ path_item_id: pathItemId, resource_type: resourceType })
    }),
  askTutor: (studentProfileId: number, courseId: number, question: string) =>
    request<TutorAnswer>("/tutor/ask", {
      method: "POST",
      body: JSON.stringify({ student_profile_id: studentProfileId, course_id: courseId, question })
    }),
  generateQuiz: (studentProfileId: number, conceptId: number, difficulty: string) =>
    request<Quiz>("/quizzes/generate", {
      method: "POST",
      body: JSON.stringify({ student_profile_id: studentProfileId, concept_id: conceptId, difficulty })
    }),
  submitAttempt: (
    quizId: number,
    studentProfileId: number,
    answers: Record<string, unknown>,
    learningPathId: number | null,
    runPostprocessing = true
  ) =>
    request<EvaluationResult>(`/quizzes/${quizId}/attempts`, {
      method: "POST",
      body: JSON.stringify({
        student_profile_id: studentProfileId,
        answers,
        learning_path_id: learningPathId,
        run_postprocessing: runPostprocessing
      })
    }),
  getTask: (taskId: number) => request<Task>(`/tasks/${taskId}`),
  getAgentRun: (runId: number) => request<AgentRun>(`/agent-runs/${runId}`)
};
