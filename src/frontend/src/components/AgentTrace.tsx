import type { AgentRun, AgentRunStep } from "../api/types";

export type TraceAction = "profile" | "path" | "resource" | "tutor" | "quiz" | "assessment";

type TraceLine = {
  agent_type: string;
  output_summary: string;
  decision_basis: string;
};

const plannerPhasePresentation: Record<string, { stage: string }> = {
  goal_resolution: {
    stage: "目标解析"
  },
  constraint_validation: {
    stage: "约束校验"
  },
  activity_generation: {
    stage: "活动编排"
  }
};

const agentTypeLabels: Record<string, string> = {
  planner: "学习规划师",
  resource: "资源设计师",
  tutor: "答疑教师",
  quiz: "出题老师",
  evaluator: "测评教师",
  profile_updater: "画像顾问",
  retriever: "资料管理员",
  router: "学习调度员"
};

const runTypeLabels: Record<string, string> = {
  planner: "学习路径规划",
  resource: "学习资源生成",
  tutor: "教师答疑辅导",
  quiz: "练习测验生成",
  evaluator: "学习效果评估",
  profile_update: "学生画像更新",
  resource_generation: "学习资源生成",
  learning_path_planning: "学习路径规划",
  quiz_generation: "练习测验生成",
  tutor_answer: "教师答疑辅导",
  attempt_evaluation: "学习效果评估"
};

const statusLabels: Record<string, string> = {
  completed: "已完成",
  success: "已完成",
  running: "执行中",
  failed: "失败",
  pending: "等待中",
  queued: "排队中"
};

const traceRunTypes: Record<TraceAction, string[]> = {
  profile: ["profile_build", "profile_update"],
  path: ["learning_path_planning", "learning_path_replanning"],
  resource: ["resource_generation"],
  tutor: ["tutor_answer"],
  quiz: ["quiz_generation"],
  assessment: ["attempt_evaluation"]
};

const tracePresets: Record<TraceAction, TraceLine[]> = {
  profile: [
    { agent_type: "profile_updater", output_summary: "读取对话内容，抽取学习目标、基础水平和偏好线索。", decision_basis: "仅更新学生画像，不生成学习资源。" },
    { agent_type: "router", output_summary: "判断当前任务属于画像构建流程。", decision_basis: "输入包含课程困难、时间预算或资源偏好。" }
  ],
  path: [
    { agent_type: "planner", output_summary: "读取画像和课程图谱，准备生成学习顺序。", decision_basis: "优先处理短板概念和前置依赖。" },
    { agent_type: "evaluator", output_summary: "校验路径难度是否符合当前基础水平。", decision_basis: "避免直接跳到高难概念。" }
  ],
  resource: [
    { agent_type: "retriever", output_summary: "检索课程资料，筛选可追溯的参考摘录。", decision_basis: "资源生成必须绑定知识库来源。" },
    { agent_type: "resource", output_summary: "根据资源类型组织结构并准备输出。", decision_basis: "结合画像偏好和当前学习节点。" }
  ],
  tutor: [
    { agent_type: "tutor", output_summary: "理解追问意图，拆解需要解释的概念或代码问题。", decision_basis: "只围绕当前课程和学生画像作答。" },
    { agent_type: "retriever", output_summary: "检索相关课程资料，为答疑提供依据。", decision_basis: "答案需要可追溯来源。" }
  ],
  quiz: [
    { agent_type: "quiz", output_summary: "围绕当前节点生成练习题。", decision_basis: "题目难度匹配学生画像。" },
    { agent_type: "evaluator", output_summary: "检查题目覆盖面和答案解释完整性。", decision_basis: "避免题目偏离当前概念。" }
  ],
  assessment: [
    { agent_type: "evaluator", output_summary: "对照参考答案和评分规则分析作答。", decision_basis: "输出分数、反馈和掌握度变化。" },
    { agent_type: "profile_updater", output_summary: "将学习轨迹写回学生画像。", decision_basis: "画像需要随学随新。" }
  ]
};

export function InlineAgentTrace({ action, busy, runs, visible = false }: { action: TraceAction; busy: boolean; runs: AgentRun[]; visible?: boolean }) {
  const run = runs.find((item) => traceRunTypes[action].includes(item.run_type));
  if (!busy && !run && !visible) return null;

  const lines = run?.steps.length
    ? summarizeRunSteps(run.steps, action)
    : tracePresets[action];

  return (
    <section className="inline-agent-terminal" data-trace-action={action} aria-live="polite">
      <div className="terminal-header">
        <span className={`terminal-status-dot ${busy ? "terminal-status-active" : ""}`} />
        <strong>{busy ? "协作生成中" : "最近一次协作过程"}</strong>
        <code>{run ? "已完成" : busy ? "进行中" : "已保留"}</code>
      </div>
      <div className="terminal-log-list">
        {lines.map((line, index) => (
          <p key={`${line.agent_type}-${index}`} className="terminal-log-line" style={{ animationDelay: `${index * 90}ms` }}>
            <span className="terminal-time">{String(index + 1).padStart(2, "0")}</span>
            <span className="terminal-agent">{agentTypeLabels[line.agent_type] ?? line.agent_type}</span>
            <span>{line.output_summary || line.decision_basis || "正在整理当前步骤的协作结果..."}</span>
          </p>
        ))}
      </div>
    </section>
  );
}

function summarizeRunSteps(steps: AgentRunStep[], action: TraceAction): TraceLine[] {
  const plannerStages = action === "path"
    ? steps
        .filter((step) => step.agent_type === "planner")
        .map(plannerPhaseForStep)
        .filter((stage): stage is string => Boolean(stage))
    : [];
  let plannerIncluded = false;

  return steps.flatMap((step) => {
    if (action === "path" && step.agent_type === "planner") {
      if (plannerIncluded) return [];
      plannerIncluded = true;
    }
    return {
      agent_type: step.agent_type,
      output_summary: action === "path" && step.agent_type === "planner" && plannerStages.length
        ? `依次完成${joinChineseList(plannerStages)}，生成可执行的学习节点顺序与活动安排。`
        : userFacingStepSummary(step, action),
      decision_basis: ""
    };
  });
}

function plannerPhaseForStep(step: AgentRunStep): string | undefined {
  const phase = `${step.input_summary} ${step.decision_basis}`.match(/phase=([a-z_]+)/)?.[1];
  return phase ? plannerPhasePresentation[phase]?.stage : undefined;
}

function joinChineseList(items: string[]): string {
  if (items.length < 2) return items[0] ?? "路径规划";
  return `${items.slice(0, -1).join("、")}和${items.at(-1)}`;
}

function userFacingStepSummary(step: AgentRunStep, action: TraceAction): string {
  if (step.agent_type === "router") {
    if (action === "resource") return "识别到你要生成学习资源，并把任务分配给资料管理员、资源设计师和测评教师。";
    if (action === "profile") return "识别到你正在补充学习情况，并把内容交给画像顾问更新学生画像。";
    if (action === "path") return "识别到你要规划学习路线，并把任务交给学习规划师。";
    return "识别本次学习任务，并安排合适的智能体协作。";
  }
  if (step.agent_type === "retriever") return "从课程知识库中查找与当前主题最相关的资料摘录，作为生成依据。";
  if (step.agent_type === "resource") return "根据当前学习节点、学生画像和检索到的资料，组织成选定类型的学习资源。";
  if (step.agent_type === "evaluator") {
    if (action === "resource") return "检查生成内容是否贴合资料来源、资源类型和当前学习目标。";
    if (action === "quiz") return "检查题目难度、答案解释和当前学习节点是否匹配。";
    return "评估本次结果是否适合当前学生状态。";
  }
  if (step.agent_type === "profile_updater") return "从对话和学习行为中提取目标、基础、偏好和薄弱点，更新学生画像。";
  if (step.agent_type === "planner") return "结合学生画像、课程图谱和掌握情况，规划下一步学习顺序。";
  if (step.agent_type === "tutor") return "根据学生问题和课程资料，组织可追溯的答疑解释。";
  if (step.agent_type === "quiz") return "围绕当前知识点生成练习题，并控制题目难度。";
  return step.output_summary || step.decision_basis || "完成当前协作步骤。";
}
