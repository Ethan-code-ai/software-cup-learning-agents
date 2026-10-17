import type { ReactNode } from "react";

type StepKey = "home" | "profile" | "kb" | "path" | "resource" | "tutor" | "quiz" | "assess";

type AgentId = "orchestrator" | "profile" | "retriever" | "planner" | "resource" | "tutor" | "quiz" | "evaluator";

const agentRoster: Array<{ id: AgentId; name: string; role: string }> = [
  { id: "orchestrator", name: "学习调度员", role: "识别学习意图，拆解任务并安排角色协同" },
  { id: "profile", name: "画像顾问", role: "从对话和学习行为中维护动态学生画像" },
  { id: "retriever", name: "资料管理员", role: "检索课程知识库，提供可追溯资料摘录" },
  { id: "planner", name: "学习规划师", role: "结合画像、知识图谱和掌握度生成学习路径" },
  { id: "resource", name: "资源设计师", role: "生成讲解文档、题库、导图、拓展阅读和实操案例" },
  { id: "tutor", name: "答疑教师", role: "基于课程资料进行多轮答疑和引导解释" },
  { id: "quiz", name: "出题教师", role: "围绕当前节点生成练习题并控制难度" },
  { id: "evaluator", name: "测评教师", role: "评估学习效果，并把表现反馈给画像和路径" }
];

const stepAgents: Record<StepKey, { lead: AgentId; support: AgentId[] }> = {
  home: { lead: "orchestrator", support: ["profile", "retriever", "planner", "resource", "tutor", "quiz", "evaluator"] },
  profile: { lead: "profile", support: ["orchestrator"] },
  kb: { lead: "retriever", support: ["orchestrator"] },
  path: { lead: "planner", support: ["profile", "retriever", "evaluator"] },
  resource: { lead: "resource", support: ["retriever", "profile", "evaluator"] },
  tutor: { lead: "tutor", support: ["retriever", "profile"] },
  quiz: { lead: "quiz", support: ["retriever", "evaluator"] },
  assess: { lead: "evaluator", support: ["profile", "planner"] }
};

export default function MultiAgentOverview({ activeStep }: { activeStep: StepKey }) {
  const active = stepAgents[activeStep];
  const activeIds = new Set<AgentId>([active.lead, ...active.support]);
  const leadAgent = agentRoster.find((agent) => agent.id === active.lead);
  const visibleAgents = activeStep === "home" ? agentRoster : agentRoster.filter((agent) => activeIds.has(agent.id));

  return (
    <section className="agent-overview">
      <div className="section-heading">
        <div>
          <p className="eyebrow">{activeStep === "home" ? "多智能体体系" : "当前协同团队"}</p>
          <h2>{activeStep === "home" ? "八个角色各自负责独立任务，共同完成个性化学习闭环" : "主导角色牵引流程，协作角色按需补充能力"}</h2>
        </div>
        <span className="orchestration-badge">
          主导：{leadAgent?.name ?? "学习调度员"} / 协作：{active.support.length} 个
        </span>
      </div>

      <div className="agent-grid">
        {visibleAgents.map((agent) => {
          const isLead = active.lead === agent.id;
          const isActive = activeIds.has(agent.id);
          return (
            <article key={agent.id} className={`agent-card ${isLead ? "agent-lead" : isActive ? "agent-support" : ""}`}>
              <span className="agent-status-badge">{isLead ? "主导" : isActive ? "协作" : "待命"}</span>
              <div className="agent-card-inner">
                <span className="agent-icon-base" aria-hidden="true">
                  <AgentIcon type={agent.id} />
                </span>
                <div>
                  <h3>{agent.name}</h3>
                  <p>{agent.role}</p>
                </div>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}

function AgentIcon({ type }: { type: AgentId }) {
  const common = {
    className: "agent-icon-svg",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.7,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const
  };

  const paths: Record<AgentId, ReactNode> = {
    orchestrator: (
      <>
        <path d="M12 4v4" />
        <path d="M12 16v4" />
        <path d="M4 12h4" />
        <path d="M16 12h4" />
        <circle cx="12" cy="12" r="4" />
      </>
    ),
    profile: (
      <>
        <circle cx="12" cy="8" r="3.2" />
        <path d="M5.5 20a6.5 6.5 0 0 1 13 0" />
        <path d="M17.5 6.5l2 2 3-3" />
      </>
    ),
    retriever: (
      <>
        <ellipse cx="12" cy="5.5" rx="6.5" ry="2.5" />
        <path d="M5.5 5.5v7c0 1.4 2.9 2.5 6.5 2.5s6.5-1.1 6.5-2.5v-7" />
        <path d="M5.5 12.5v4c0 1.4 2.9 2.5 6.5 2.5 1.2 0 2.4-.1 3.3-.4" />
        <circle cx="18" cy="18" r="2.4" />
        <path d="m20 20 2 2" />
      </>
    ),
    planner: (
      <>
        <path d="M5 6h5" />
        <path d="M14 6h5" />
        <path d="M7.5 6v11" />
        <path d="M16.5 6v11" />
        <path d="M7.5 17h9" />
        <circle cx="7.5" cy="6" r="2" />
        <circle cx="16.5" cy="17" r="2" />
      </>
    ),
    resource: (
      <>
        <path d="M12 3 20 7.5 12 12 4 7.5 12 3Z" />
        <path d="m4 12 8 4.5 8-4.5" />
        <path d="m4 16.5 8 4.5 8-4.5" />
      </>
    ),
    tutor: (
      <>
        <path d="M5 6.5A3.5 3.5 0 0 1 8.5 3h7A3.5 3.5 0 0 1 19 6.5v5A3.5 3.5 0 0 1 15.5 15H10l-5 4v-4.8A3.5 3.5 0 0 1 3 11V6.5Z" />
        <path d="M8 8h8" />
        <path d="M8 11h5" />
      </>
    ),
    quiz: (
      <>
        <path d="M8 4h8" />
        <path d="M7 4h10a2 2 0 0 1 2 2v14H5V6a2 2 0 0 1 2-2Z" />
        <path d="m8 12 2 2 4-4" />
        <path d="M8 17h8" />
      </>
    ),
    evaluator: (
      <>
        <path d="M4 19h16" />
        <path d="M7 16v-5" />
        <path d="M12 16V7" />
        <path d="M17 16v-8" />
        <path d="M6 5h12" />
      </>
    )
  };

  return <svg {...common}>{paths[type]}</svg>;
}
