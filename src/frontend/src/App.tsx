import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import "katex/dist/katex.min.css";

import { api } from "./api/client";
import type {
  AgentRun,
  AgentRunStep,
  Concept,
  ConceptGraph,
  DemoDataStatus,
  DocumentIngestionResponse,
  DocumentReindexResponse,
  EvaluationResult,
  GeneratedResource,
  KnowledgeSearchResult,
  LearningFlow,
  LearningPath,
  LearningPathItem,
  ManagedDocument,
  Quiz,
  StudentProfile,
  StudentProfileHistory
} from "./api/types";
import DashboardSidebar from "./components/Sidebar";
import KnowledgePanel from "./components/KnowledgePanel";
import { AgentLoading, DebugModal, EmptyState, Metric, Panel, StatusLine } from "./components/common";
import { InlineAgentTrace } from "./components/AgentTrace";
import type { TraceAction } from "./components/AgentTrace";
import { ProfileDimensionList, ProfileHistoryPanel, ProfileSkeleton } from "./components/ProfilePanels";
import HomeDashboard from "./components/HomeDashboard";
import { PersistentLearningPathRail } from "./components/LearningPath";
import PathStep from "./features/path/PathStep";
import ResourceStep from "./features/resource/ResourceStep";
import TutorStep from "./features/tutor/TutorStep";
import QuizStep from "./features/quiz/QuizStep";

type BusyAction =
  | "load-demo"
  | "reset-demo"
  | "build-profile"
  | "delete-profile"
  | "import-knowledge"
  | "upload-knowledge"
  | "refresh-documents"
  | "delete-document"
  | "reindex-document"
  | "search-knowledge"
  | "create-path"
  | "complete-path-item"
  | "generate-resource"
  | "ask-tutor"
  | "generate-quiz"
  | "submit-attempt"
  | "sync-profile";

const busyTraceActions: Partial<Record<BusyAction, TraceAction>> = {
  "build-profile": "profile",
  "create-path": "path",
  "generate-resource": "resource",
  "ask-tutor": "tutor",
  "generate-quiz": "quiz",
  "submit-attempt": "assessment",
  "sync-profile": "assessment"
};

type StepKey = "home" | "profile" | "kb" | "path" | "resource" | "tutor" | "quiz" | "assess";

type TutorMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  sourceRefs?: Array<Record<string, unknown>>;
  safetyStatus?: "passed" | "blocked" | "degraded";
  safetyMessage?: string | null;
};

const profileLabels: Record<string, string> = {
  weak_foundation: "基础薄弱型",
  exam_sprint: "考试冲刺型",
  algorithm_practice: "算法训练型"
};

const resourceOptions = [
  { type: "guided_note", label: "讲解文档" },
  { type: "practice_questions", label: "练习题库" },
  { type: "mind_map", label: "思维导图" },
  { type: "extended_reading", label: "拓展阅读" },
  { type: "coding_case", label: "代码实操" },
  { type: "teaching_video", label: "教学动画" }
] as const;

const stepFlow: Array<{ key: StepKey; label: string; desc: string }> = [
  { key: "home", label: "工作台首页", desc: "总览学习状态、资料接入和下一步学习动作" },
  { key: "profile", label: "学生画像", desc: "通过自然语言对话抽取特征，形成六维动态画像" },
  { key: "kb", label: "知识库", desc: "导入课程资料，检索可追溯证据片段" },
  { key: "path", label: "学习路径", desc: "根据画像、课程图谱和目标规划学习顺序" },
  { key: "resource", label: "资源生成", desc: "生成文档、题库、思维导图、拓展阅读和实操案例" },
  { key: "tutor", label: "教师答疑", desc: "基于证据进行个性化答疑" },
  { key: "quiz", label: "智能测验", desc: "生成当前节点练习题并收集作答" },
  { key: "assess", label: "学习评估", desc: "评估学习效果并触发画像回写" }
];

function labelProfile(type: string): string {
  return profileLabels[type] ?? type.replaceAll("_", " ");
}

function toErrorMessage(err: unknown): string {
  if (err instanceof Error) return err.message;
  return "请求失败，请检查后端服务是否正常运行。";
}

function inferPastedSourceType(content: string): "text" | "markdown" {
  const markdownPatterns = [
    /^#{1,6}\s+/m,
    /^[-*+]\s+/m,
    /^\d+\.\s+/m,
    /```[\s\S]*?```/,
    /^\|.+\|$/m,
    /\[[^\]]+\]\([^)]+\)/,
  ];
  return markdownPatterns.some((pattern) => pattern.test(content)) ? "markdown" : "text";
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

export function App() {
  const [status, setStatus] = useState<DemoDataStatus | null>(null);
  const [profiles, setProfiles] = useState<StudentProfile[]>([]);
  const [graph, setGraph] = useState<ConceptGraph | null>(null);
  const [selectedProfileId, setSelectedProfileId] = useState<number | null>(null);
  const [profileHistory, setProfileHistory] = useState<StudentProfileHistory[]>([]);
  const [selectedPathItemId, setSelectedPathItemId] = useState<number | null>(null);
  const [profileDialogue, setProfileDialogue] = useState(
    "我最近在学习二叉树遍历和图搜索，递归边界容易出错。每天可以投入 1 小时，希望系统多给我图解、例题和代码实操。"
  );
  const [goal, setGoal] = useState("巩固二叉树遍历和图搜索，为课程小测做准备");
  const [knowledgeTitle, setKnowledgeTitle] = useState("数据结构学习笔记.md");
  const [knowledgeContent, setKnowledgeContent] = useState(
    "# 广度优先搜索与深度优先搜索\n广度优先搜索通常使用队列逐层扩展节点，适合求无权图最短路径；深度优先搜索通常使用递归或栈深入遍历，适合连通性判断、回溯和拓扑类问题。"
  );
  const [knowledgeQuery, setKnowledgeQuery] = useState("广度优先 搜索 队列 最短路径 深度优先");
  const [knowledgeFile, setKnowledgeFile] = useState<File | null>(null);
  const [knowledgeImportResult, setKnowledgeImportResult] = useState<DocumentIngestionResponse | null>(null);
  const [knowledgeReindexResult, setKnowledgeReindexResult] = useState<DocumentReindexResponse | null>(null);
  const [knowledgeDocuments, setKnowledgeDocuments] = useState<ManagedDocument[]>([]);
  const [knowledgeSearchResults, setKnowledgeSearchResults] = useState<KnowledgeSearchResult[]>([]);
  const [knowledgeError, setKnowledgeError] = useState<string | null>(null);
  const [flow, setFlow] = useState<LearningFlow | null>(null);
  const [resource, setResource] = useState<GeneratedResource | null>(null);
  const [resourceType, setResourceType] = useState<(typeof resourceOptions)[number]["type"]>("guided_note");
  const [question, setQuestion] = useState("我应该如何区分广度优先搜索和深度优先搜索？");
  const [tutorMessages, setTutorMessages] = useState<TutorMessage[]>([]);
  const [quiz, setQuiz] = useState<Quiz | null>(null);
  const [attemptText, setAttemptText] = useState("");
  const [evaluation, setEvaluation] = useState<EvaluationResult | null>(null);
  const [autoProfileUpdate, setAutoProfileUpdate] = useState<string | null>(null);
  const [learningTraceUpdateNotice, setLearningTraceUpdateNotice] = useState<string | null>(null);
  const [autoProfileUpdateEnabled, setAutoProfileUpdateEnabled] = useState(true);
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [retainedTraces, setRetainedTraces] = useState<TraceAction[]>([]);
  const [busy, setBusy] = useState<BusyAction | null>(null);
  const [booting, setBooting] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [traceOpen, setTraceOpen] = useState(false);
  const [debugOpen, setDebugOpen] = useState(false);
  const [activeStep, setActiveStep] = useState<StepKey>("home");
  const [profileDraft, setProfileDraft] = useState("");
  const chatScrollRef = useRef<HTMLDivElement | null>(null);
  const selectedProfileIdRef = useRef<number | null>(null);

  const latestProfile = profiles[0] ?? null;
  const pathItems = flow?.learning_path.items ?? [];
  const selectedItem = pathItems.find((item) => item.id === selectedPathItemId) ?? pathItems[0] ?? null;
  const selectedConcept = useMemo<Concept | null>(() => {
    if (!graph) return null;
    if (selectedItem) return graph.concepts.find((concept) => concept.id === selectedItem.concept_id) ?? null;
    return graph.concepts[0] ?? null;
  }, [graph, selectedItem]);

  const canCreatePath = Boolean(selectedProfileId && status?.course_id);
  const canUseLoop = Boolean(selectedProfileId && status?.course_id && selectedConcept);
  const stepInfo = stepFlow.find((step) => step.key === activeStep) ?? stepFlow[0];
  const profileQuickReplies = [
    "我这学期数据结构最吃力，图搜索和递归容易混淆，每天能学 1 小时。",
    "我想备考人工智能课程，希望多给我图解、例题和代码实操。",
    "我基础一般，喜欢先看案例再总结概念，希望学习路径更细一些。"
  ];

  async function runTask(action: BusyAction, task: () => Promise<void>) {
    const traceAction = busyTraceActions[action];
    if (traceAction) {
      setRetainedTraces((current) => (current.includes(traceAction) ? current : [...current, traceAction]));
    }
    setBusy(action);
    setError(null);
    try {
      await task();
    } catch (err) {
      const message = toErrorMessage(err);
      setError(message);
      if (action.includes("knowledge") || action.includes("document")) setKnowledgeError(message);
    } finally {
      setBusy(null);
    }
  }

  async function refreshBaseData() {
    const nextStatus = await api.getDemoStatus();
    setStatus(nextStatus);
    const nextProfiles = await api.listProfiles();
    setProfiles(nextProfiles);
    const nextSelectedId = nextProfiles.find((profile) => profile.id === selectedProfileId)?.id ?? nextProfiles[0]?.id ?? null;
    if (nextSelectedId) setProfileHistory(await api.getProfileHistory(nextSelectedId));
    setSelectedProfileId((current) =>
      current && nextProfiles.some((profile) => profile.id === current) ? current : nextProfiles[0]?.id ?? null
    );
    if (nextStatus.course_id) {
      setGraph(await api.getCourseGraph(nextStatus.course_id));
      setKnowledgeDocuments(await api.listCourseDocuments(nextStatus.course_id));
    } else {
      setGraph(null);
      setKnowledgeDocuments([]);
    }
  }

  async function appendRun(runId: number | null) {
    if (!runId) return;
    const run = await api.getAgentRun(runId);
    setRuns((current) => [run, ...current.filter((item) => item.id !== run.id)].slice(0, 10));
  }

  function resetLoopOutputs() {
    setResource(null);
    setTutorMessages([]);
    setQuiz(null);
    setAttemptText("");
    setEvaluation(null);
    setAutoProfileUpdate(null);
    setLearningTraceUpdateNotice(null);
  }

  function replaceOrAppendProfile(nextProfile: StudentProfile) {
    setProfiles((current) => [nextProfile, ...current.filter((profile) => profile.id !== nextProfile.id)]);
    setSelectedProfileId(nextProfile.id);
    setFlow(null);
    setSelectedPathItemId(null);
    setRuns([]);
    resetLoopOutputs();
  }

  function refreshSelectedProfile(nextProfile: StudentProfile) {
    setProfiles((current) => current.map((profile) => (profile.id === nextProfile.id ? nextProfile : profile)));
    setSelectedProfileId(nextProfile.id);
  }

  async function refreshProfileHistory(profileId: number) {
    setProfileHistory(await api.getProfileHistory(profileId));
  }

  async function refreshKnowledgeDocuments() {
    if (!status?.course_id) return;
    setKnowledgeError(null);
    setKnowledgeDocuments(await api.listCourseDocuments(status.course_id));
  }

  async function pollQuizPostprocessing(taskId: number, profileId: number, pathId: number | null) {
    try {
      for (let attempt = 0; attempt < 180; attempt += 1) {
        const task = await api.getTask(taskId);
        if (task.status === "failed") {
          setAutoProfileUpdate(`成绩已保存，但画像与路径后台更新失败：${task.error ?? "未知错误"}`);
          return;
        }
        if (task.status === "completed") {
          const [nextProfile, nextHistory, nextPath] = await Promise.all([
            api.getProfile(profileId),
            api.getProfileHistory(profileId),
            pathId === null ? Promise.resolve(null) : api.getLearningPath(pathId)
          ]);
          setProfiles((current) => current.map((profile) => (profile.id === nextProfile.id ? nextProfile : profile)));
          if (selectedProfileIdRef.current === profileId) {
            setProfileHistory(nextHistory);
          }
          if (nextPath !== null) {
            setFlow((current) =>
              current?.learning_path.id === nextPath.id ? { ...current, learning_path: nextPath } : current
            );
          }
          setAutoProfileUpdate("成绩已保存，画像与当前学习路径已在后台刷新。");
          return;
        }
        setAutoProfileUpdate("成绩已返回，画像与当前学习路径正在后台更新。");
        await delay(1000);
      }
      setAutoProfileUpdate("成绩已保存，后台更新仍在进行，可稍后查看任务状态。");
    } catch (err) {
      setAutoProfileUpdate(`成绩已保存，但后台任务状态查询失败：${toErrorMessage(err)}`);
    }
  }

  async function pollProfilePostprocessing(taskId: number, profileId: number) {
    setLearningTraceUpdateNotice("内容已返回，画像正在后台更新。");
    try {
      for (let attempt = 0; attempt < 120; attempt += 1) {
        const task = await api.getTask(taskId);
        if (task.status === "failed") {
          setLearningTraceUpdateNotice(`内容已返回，但画像后台更新失败：${task.error ?? "未知错误"}`);
          return;
        }
        if (task.status === "completed") {
          const [nextProfile, nextHistory] = await Promise.all([
            api.getProfile(profileId),
            api.getProfileHistory(profileId)
          ]);
          setProfiles((current) => current.map((profile) => (profile.id === nextProfile.id ? nextProfile : profile)));
          if (selectedProfileIdRef.current === profileId) {
            setProfileHistory(nextHistory);
          }
          setLearningTraceUpdateNotice("内容已返回，画像已在后台更新。");
          return;
        }
        await delay(1000);
      }
      setLearningTraceUpdateNotice("内容已返回，画像后台更新仍在进行，可稍后查看任务状态。");
    } catch (err) {
      setLearningTraceUpdateNotice(`内容已返回，但画像后台任务状态查询失败：${toErrorMessage(err)}`);
    }
  }

  async function submitQuizAttempt() {
    if (!quiz || !selectedProfileId || !attemptText.trim()) return;
    setBusy("submit-attempt");
    setError(null);
    setAutoProfileUpdate(null);
    try {
      const pathId = flow?.learning_path.id ?? null;
      const nextEvaluation = await api.submitAttempt(
        quiz.id,
        selectedProfileId,
        { answer: attemptText },
        pathId,
        autoProfileUpdateEnabled
      );
      setEvaluation(nextEvaluation);
      await appendRun(nextEvaluation.agent_run_id);
      setActiveStep("assess");
      if (!autoProfileUpdateEnabled) {
        setAutoProfileUpdate("成绩已保存，画像与路径后台更新已关闭。");
        return;
      }
      if (nextEvaluation.postprocessing_task_id !== null) {
        setAutoProfileUpdate("成绩已返回，画像与当前学习路径正在后台更新。");
        void pollQuizPostprocessing(nextEvaluation.postprocessing_task_id, selectedProfileId, pathId);
      }
    } catch (err) {
      setError(toErrorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  useEffect(() => {
    selectedProfileIdRef.current = selectedProfileId;
  }, [selectedProfileId]);

  useEffect(() => {
    let active = true;
    setBooting(true);
    refreshBaseData()
      .catch((err) => {
        if (active) setError(toErrorMessage(err));
      })
      .finally(() => {
        if (active) setBooting(false);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (activeStep !== "tutor") return;
    chatScrollRef.current?.scrollTo({
      top: chatScrollRef.current.scrollHeight,
      behavior: "smooth"
    });
  }, [tutorMessages, busy, activeStep]);

  function handleGenerateQuiz() {
    void runTask("generate-quiz", async () => {
      if (!selectedConcept || !selectedProfileId) return;
      const nextQuiz = await api.generateQuiz(selectedProfileId, selectedConcept.id, "medium");
      setQuiz(nextQuiz);
      await appendRun(nextQuiz.agent_run_id);
    });
  }

  function handleAskTutor() {
    void runTask("ask-tutor", async () => {
      if (!selectedProfileId || !status?.course_id) return;
      const submittedQuestion = question.trim();
      const messageStamp = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
      setQuestion("");
      setTutorMessages((current) => [
        ...current,
        { id: `user-${messageStamp}`, role: "user", content: submittedQuestion }
      ]);
      const nextAnswer = await api.askTutor(selectedProfileId, status.course_id, submittedQuestion);
      setTutorMessages((current) => [
        ...current,
        {
          id: `assistant-${messageStamp}`,
          role: "assistant",
          content: nextAnswer.answer,
          sourceRefs: nextAnswer.source_refs,
          safetyStatus: nextAnswer.safety_status,
          safetyMessage: nextAnswer.safety_message
        }
      ]);
      await appendRun(nextAnswer.agent_run_id);
      if (nextAnswer.postprocessing_task_id !== null) {
        void pollProfilePostprocessing(nextAnswer.postprocessing_task_id, selectedProfileId);
      }
    });
  }

  function handleCompleteSelectedPathItem() {
    if (!selectedItem) return;
    void runTask("complete-path-item", async () => {
      const nextPath = await api.completePathItem(selectedItem.id);
      setFlow((current) => current ? { ...current, learning_path: nextPath } : current);
      if (selectedProfileId) {
        refreshSelectedProfile(await api.getProfile(selectedProfileId));
        await refreshProfileHistory(selectedProfileId);
      }
    });
  }

  const profileStep = (
    <div className="content-grid profile-content-grid">
      <Panel title="对话式学生画像" kicker="画像随学随新">
        <div className="profile-onboarding">
          <div className="onboarding-messages">
            <article className="onboarding-bubble onboarding-bubble-guide">
              <span>学习管家</span>
              <p>同学你好，我是你的专属学习管家。这学期哪门课程最让你头疼？你希望我用什么方式帮你学？</p>
            </article>
            {(profileDialogue || profileDraft) ? (
              <article className="onboarding-bubble onboarding-bubble-user">
                <span>你的回复</span>
                <p>{profileDraft || profileDialogue}</p>
              </article>
            ) : null}
          </div>
          <div className="quick-reply-row" aria-label="快捷回复">
            {profileQuickReplies.map((reply) => (
              <button key={reply} className="pill-button" type="button" onClick={() => setProfileDraft(reply)}>
                {reply}
              </button>
            ))}
          </div>
          <div className="onboarding-composer">
            <input
              className="onboarding-input"
              data-testid="profile-dialogue"
              value={profileDraft}
              onChange={(event) => setProfileDraft(event.target.value)}
              aria-label="画像对话内容"
              placeholder="例如：我基础一般，图搜索总出错，每天晚上能学 1 小时..."
            />
            <button
              className="chat-send-button onboarding-send"
              data-testid="build-profile-button"
              disabled={!profileDraft.trim() || busy !== null}
              onClick={() =>
                void runTask("build-profile", async () => {
                  const submitted = profileDraft.trim();
                  setProfileDialogue(submitted);
                  const nextProfile = await api.createProfileFromDialogue({ dialogue: submitted });
                  replaceOrAppendProfile(nextProfile);
                  await refreshProfileHistory(nextProfile.id);
                  setProfileDraft("");
                })
              }
            >
              {busy === "build-profile" ? "分析中" : "生成画像"}
            </button>
          </div>
          <InlineAgentTrace action="profile" busy={busy === "build-profile"} runs={runs} visible={retainedTraces.includes("profile")} />
        </div>
        <div className="profile-summary-stack">
          {latestProfile ? (
            <article className="profile-current-card" data-testid="profile-option">
              <div>
                <p className="eyebrow">最新画像</p>
                <strong>{labelProfile(latestProfile.profile_type)}</strong>
                <span>{latestProfile.goal}</span>
              </div>
              {latestProfile.id !== selectedProfileId ? (
                <button
                  className="small-button"
                  onClick={() => {
                    setSelectedProfileId(latestProfile.id);
                    setFlow(null);
                    setSelectedPathItemId(null);
                    resetLoopOutputs();
                  }}
                >
                  使用此画像
                </button>
              ) : null}
            </article>
          ) : null}
          {busy === "build-profile" ? (
            <ProfileSkeleton />
          ) : latestProfile ? (
            <>
              <ProfileDimensionList profile={latestProfile} />
              <ProfileHistoryPanel history={profileHistory} />
            </>
          ) : (
            <EmptyState text="请先通过对话生成一个学生画像。" />
          )}
        </div>
      </Panel>
    </div>
  );

  const knowledgeStep = (
    <div className="knowledge-step">
      <KnowledgePanel
        status={status}
        busy={busy}
        knowledgeTitle={knowledgeTitle}
        setKnowledgeTitle={setKnowledgeTitle}
        knowledgeContent={knowledgeContent}
        setKnowledgeContent={setKnowledgeContent}
        knowledgeFile={knowledgeFile}
        setKnowledgeFile={setKnowledgeFile}
        knowledgeImportResult={knowledgeImportResult}
        knowledgeReindexResult={knowledgeReindexResult}
        knowledgeDocuments={knowledgeDocuments}
        knowledgeError={knowledgeError}
        knowledgeQuery={knowledgeQuery}
        setKnowledgeQuery={setKnowledgeQuery}
        knowledgeSearchResults={knowledgeSearchResults}
        onRunTask={runTask}
        onImport={async () => {
          if (!status?.course_id) return;
          setKnowledgeError(null);
          setKnowledgeReindexResult(null);
          const result = await api.ingestCourseDocument(status.course_id, {
            title: knowledgeTitle,
            source_type: inferPastedSourceType(knowledgeContent),
            content: knowledgeContent
          });
          setKnowledgeImportResult(result);
          setKnowledgeSearchResults([]);
          await refreshKnowledgeDocuments();
        }}
        onUpload={async () => {
          if (!status?.course_id || !knowledgeFile) return;
          setKnowledgeError(null);
          setKnowledgeReindexResult(null);
          const result = await api.uploadCourseDocument(status.course_id, knowledgeFile, {
            title: knowledgeTitle.trim() || knowledgeFile.name,
            visibility: "course"
          });
          setKnowledgeImportResult(result);
          setKnowledgeSearchResults([]);
          await refreshKnowledgeDocuments();
        }}
        onRefresh={refreshKnowledgeDocuments}
        onDelete={async (documentId) => {
          await api.deleteDocument(documentId);
          setKnowledgeImportResult(null);
          setKnowledgeReindexResult(null);
          setKnowledgeSearchResults([]);
          await refreshKnowledgeDocuments();
        }}
        onReindex={async (documentId) => {
          setKnowledgeReindexResult(await api.reindexDocument(documentId));
        }}
        onSearch={async () => {
          if (!status?.course_id) return;
          const result = await api.searchKnowledge(status.course_id, knowledgeQuery, 4);
          setKnowledgeSearchResults(result.results);
        }}
      />
    </div>
  );

  const pathStep = (
    <PathStep
      goal={goal}
      onGoalChange={setGoal}
      canCreatePath={canCreatePath}
      busy={busy}
      error={error}
      runs={runs}
      traceVisible={retainedTraces.includes("path")}
      flow={flow}
      graph={graph}
      pathItems={pathItems}
      selectedItem={selectedItem}
      selectedConcept={selectedConcept}
      onCreatePath={() =>
        void runTask("create-path", async () => {
          if (!selectedProfileId || !status?.course_id) return;
          const nextFlow = await api.createLearningPath(selectedProfileId, status.course_id, goal);
          setFlow(nextFlow);
          setSelectedPathItemId(nextFlow.learning_path.items[0]?.id ?? null);
          await appendRun(nextFlow.agent_run.id);
          resetLoopOutputs();
        })
      }
      onSelectPathItem={(item) => setSelectedPathItemId(item.id)}
      onCompleteItem={handleCompleteSelectedPathItem}
    />
  );

  const resourceStep = (
    <ResourceStep
      busy={busy}
      selectedItem={selectedItem}
      selectedConcept={selectedConcept}
      resource={resource}
      resourceType={resourceType}
      resourceOptions={resourceOptions}
      runs={runs}
      traceVisible={retainedTraces.includes("resource")}
      learningTraceUpdateNotice={learningTraceUpdateNotice}
      onResourceTypeChange={(type) => setResourceType(type as (typeof resourceOptions)[number]["type"])}
      onGenerate={() =>
        void runTask("generate-resource", async () => {
          if (!selectedItem) return;
          const nextResource = await api.generateResource(selectedItem.id, resourceType);
          setResource(nextResource);
          await appendRun(nextResource.agent_run_id);
          if (nextResource.postprocessing_task_id !== null && selectedProfileId !== null) {
            void pollProfilePostprocessing(nextResource.postprocessing_task_id, selectedProfileId);
          }
        })
      }
    />
  );

  const tutorStep = (
    <TutorStep
      busy={busy}
      canUseLoop={canUseLoop}
      question={question}
      onQuestionChange={setQuestion}
      messages={tutorMessages}
      chatScrollRef={chatScrollRef}
      runs={runs}
      traceVisible={retainedTraces.includes("tutor")}
      learningTraceUpdateNotice={learningTraceUpdateNotice}
      onAskTutor={handleAskTutor}
    />
  );

  const quizStep = (
    <QuizStep
      busy={busy}
      quiz={quiz}
      canGenerateQuiz={Boolean(selectedConcept && selectedProfileId)}
      attemptText={attemptText}
      onAttemptTextChange={setAttemptText}
      autoProfileUpdateEnabled={autoProfileUpdateEnabled}
      onAutoProfileUpdateEnabledChange={setAutoProfileUpdateEnabled}
      runs={runs}
      traceVisible={retainedTraces.includes("quiz")}
      onGenerateQuiz={handleGenerateQuiz}
      onSubmitAttempt={() => void submitQuizAttempt()}
    />
  );

  const assessStep = (
    <Panel title="学习效果评估" kicker="画像回写">
      {evaluation ? (
        <div className="space-y-4">
          <Metric label="综合得分" value={`${Math.round(evaluation.score * 100)}%`} />
          <p className="feedback" data-testid="evaluator-feedback">{evaluation.feedback}</p>
          {autoProfileUpdate ? <p className="profile-update-note" data-testid="auto-profile-update">{autoProfileUpdate}</p> : null}
          <div className="update-list">
            {evaluation.mastery_updates.map((update, index) => (
              <article key={index} className="update-card">
                <strong>概念 {String(update.concept_id ?? "未知")}</strong>
                <span>掌握度：{String(update.mastery_score ?? "暂无")}</span>
                <p>{String(update.evidence ?? "暂无证据说明")}</p>
              </article>
            ))}
          </div>
        </div>
      ) : (
        <EmptyState text="提交作答后，这里会展示得分、反馈、掌握度变化和画像更新原因。" />
      )}
    </Panel>
  );

  const homeStep = (
    <HomeDashboard
      flow={flow}
      selectedItem={selectedItem}
      latestProfile={latestProfile}
    />
  );

  const stepContent: Record<StepKey, ReactNode> = {
    home: homeStep,
    profile: profileStep,
    kb: knowledgeStep,
    path: pathStep,
    resource: resourceStep,
    tutor: tutorStep,
    quiz: quizStep,
    assess: assessStep
  };

  return (
    <main className="app-shell" data-step={activeStep}>
      <DashboardSidebar activeStep={activeStep} onSelect={setActiveStep} />
      <div className="dashboard-workspace">
      <header className="top-bar">
        <div>
          <p className="eyebrow">第十五届中国软件杯 A 组赛题演示</p>
          <h1>个性化学习资源生成与教师协同工作台</h1>
        </div>
        <div className="top-actions">
          <button
            className="icon-button"
            type="button"
            aria-label="打开设置与调试"
            title="设置与调试"
            onClick={() => setDebugOpen(true)}
          >
            ⚙
          </button>
        </div>
      </header>

      <section className="app-main">
        <div className="toolbar">
          <div>
            <p className="eyebrow">当前步骤</p>
            <h2>{stepInfo.label}</h2>
            <span>{stepInfo.desc}</span>
          </div>
        </div>

        <div className="step-body">{stepContent[activeStep]}</div>
      </section>

      <footer className="app-footer-badge">Powered by 科大讯飞星火大模型</footer>
      </div>
      <PersistentLearningPathRail
        items={pathItems}
        concepts={graph?.concepts ?? []}
        selectedId={selectedItem?.id ?? null}
        onSelect={(item) => setSelectedPathItemId(item.id)}
        onOpenPath={() => setActiveStep("path")}
        busy={busy !== null}
        onCompleteCurrent={handleCompleteSelectedPathItem}
      />
      <DebugModal
        open={debugOpen}
        busy={busy}
        booting={booting}
        error={error}
        onClose={() => setDebugOpen(false)}
        onLoadDemo={() =>
          void runTask("load-demo", async () => {
            await api.loadDemoData();
            await refreshBaseData();
          })
        }
        onResetDemo={() =>
          void runTask("reset-demo", async () => {
            await api.resetDemoUserData();
            await refreshBaseData();
            setFlow(null);
            setSelectedPathItemId(null);
            setRuns([]);
            resetLoopOutputs();
          })
        }
      />
    </main>
  );
}

