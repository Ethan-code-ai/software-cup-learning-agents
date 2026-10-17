type StepKey = "home" | "profile" | "kb" | "path" | "resource" | "tutor" | "quiz" | "assess";


const stepFlow: Array<{ key: StepKey; label: string; desc: string }> = [
  { key: "home", label: "工作台首页", desc: "总览学习状态、资料接入和下一步学习动作" },
  { key: "profile", label: "学生画像", desc: "通过自然语言对话抽取特征，形成六维动态画像" },
  { key: "kb", label: "知识库", desc: "导入课程资料，检索可追溯参考资料" },
  { key: "path", label: "学习路径", desc: "根据画像、课程图谱和目标规划学习顺序" },
  { key: "resource", label: "资源生成", desc: "生成文档、题库、思维导图、拓展阅读和实操案例" },
  { key: "tutor", label: "教师答疑", desc: "基于证据进行个性化答疑" },
  { key: "quiz", label: "智能测验", desc: "生成当前节点练习题并收集作答" },
  { key: "assess", label: "学习评估", desc: "评估学习效果并触发画像回写" }
];


function SidebarStepIcon({ type }: { type: StepKey }) {
  const common = {
    width: 20,
    height: 20,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.7,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const
  };

  if (type === "home") return <svg {...common}><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></svg>;
  if (type === "profile") return <svg {...common}><circle cx="12" cy="8" r="4" /><path d="M5 21a7 7 0 0 1 14 0" /></svg>;
  if (type === "kb") return <svg {...common}><path d="M4 6c0-1.1 3.6-2 8-2s8 .9 8 2-3.6 2-8 2-8-.9-8-2Z" /><path d="M4 6v6c0 1.1 3.6 2 8 2s8-.9 8-2V6" /><path d="M4 12v6c0 1.1 3.6 2 8 2s8-.9 8-2v-6" /></svg>;
  if (type === "path") return <svg {...common}><circle cx="6" cy="18" r="2" /><circle cx="18" cy="6" r="2" /><path d="M8 18h3.5a3.5 3.5 0 0 0 0-7H11a3.5 3.5 0 0 1 0-7h5" /></svg>;
  if (type === "resource") return <svg {...common}><path d="m12 3 8 4.5-8 4.5-8-4.5L12 3Z" /><path d="m4 12 8 4.5 8-4.5" /><path d="m4 16.5 8 4.5 8-4.5" /></svg>;
  if (type === "tutor") return <svg {...common}><path d="M21 12a8 8 0 0 1-8 8H7l-4 2 1.5-4.5A8 8 0 1 1 21 12Z" /><path d="M8 11h8" /><path d="M8 15h5" /></svg>;
  if (type === "quiz") return <svg {...common}><rect x="5" y="3" width="14" height="18" rx="2" /><path d="m9 9 1.5 1.5L14 7" /><path d="M9 15h6" /></svg>;
  return <svg {...common}><path d="M4 19V5" /><path d="M4 19h16" /><path d="M8 16v-5" /><path d="M12 16V8" /><path d="M16 16v-3" /></svg>;
}

function DashboardSidebar({ activeStep, onSelect }: { activeStep: StepKey; onSelect: (key: StepKey) => void }) {
  return (
    <aside className="dashboard-sidebar" aria-label="学习流程侧边栏">
      <div className="sidebar-brand">
        <span className="brand-mark">AI</span>
        <div>
          <strong>多智能体协同工作台</strong>
          <p>个性化学习流程</p>
        </div>
      </div>

      <nav className="sidebar-nav" aria-label="学习步骤导航">
        <p className="sidebar-section-label">学习流程</p>
        {stepFlow.map((step) => {
          const selected = activeStep === step.key;
          return (
            <button
              key={step.key}
              className={`sidebar-nav-item ${selected ? "sidebar-nav-active" : ""}`}
              data-step={step.key}
              type="button"
              onClick={() => onSelect(step.key)}
              aria-current={selected ? "page" : undefined}
            >
              <span className="sidebar-nav-icon" aria-hidden="true"><SidebarStepIcon type={step.key} /></span>
              <span className="sidebar-nav-copy">
                <strong>{step.label}</strong>
              </span>
              <span className="sidebar-nav-status" aria-hidden="true" />
            </button>
          );
        })}
      </nav>

      <div className="sidebar-footer-note">
        <span>当前视图</span>
        <strong>{stepFlow.find((step) => step.key === activeStep)?.label}</strong>
      </div>
    </aside>
  );
}


export { SidebarStepIcon };
export default DashboardSidebar;
