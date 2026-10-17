import type { LearningFlow, LearningPathItem, StudentProfile } from "../api/types";
import MultiAgentOverview from "./AgentOverview";

export default function HomeDashboard({
  flow,
  selectedItem,
  latestProfile
}: {
  flow: LearningFlow | null;
  selectedItem: LearningPathItem | null;
  latestProfile: StudentProfile | null;
}) {
  const pathItems = flow?.learning_path.items ?? [];
  const completedCount = pathItems.filter((item) => item.status === "completed").length;
  const progress = pathItems.length ? Math.round((completedCount / pathItems.length) * 100) : 0;
  const totalMinutes = pathItems.reduce((sum, item) => sum + item.estimated_minutes, 0);

  return (
    <section className="home-dashboard">
      <div className="home-hero commercial-hero">
        <div>
          <p className="eyebrow">学习驾驶舱</p>
          <h2>数据结构个性化学习工作台</h2>
          <span>
            系统以学生画像为核心，联动课程知识库、学习路径、资源生成、教师答疑、智能测验和评估反馈，形成可持续更新的学习闭环。
          </span>
        </div>
        <div className="hero-course-card" aria-label="当前课程状态">
          <span>当前课程</span>
          <strong>数据结构</strong>
          <small>{selectedItem ? `正在学习：${selectedItem.title}` : "等待生成学习路径"}</small>
        </div>
      </div>

      <section className="dashboard-overview-grid">
        <article className="dashboard-progress-card">
          <div className="dashboard-card-head">
            <div>
              <p className="eyebrow">学习进度</p>
              <h3>{progress}%</h3>
            </div>
            <span>{completedCount}/{pathItems.length || 0} 节点</span>
          </div>
          <div className="progress-track">
            <i style={{ width: `${progress}%` }} />
          </div>
          <p>{pathItems.length ? `预计总时长 ${totalMinutes} 分钟，当前建议继续推进路径中的关键节点。` : "完成画像并接入课程资料后，系统会生成可执行的学习路径。"}</p>
        </article>

        <article className="dashboard-focus-card">
          <p className="eyebrow">今日重点</p>
          <strong>{selectedItem?.title ?? (latestProfile ? "生成个性化学习路径" : "完成对话式学生画像")}</strong>
          <p>{selectedItem?.objective ?? (latestProfile ? "画像已可用，下一步建议进入学习路径模块生成闭环计划。" : "先描述课程目标、基础水平、学习时间和偏好，系统会自动构建六维画像。")}</p>
        </article>

        <article className="dashboard-profile-card">
          <p className="eyebrow">画像状态</p>
          <strong>{latestProfile ? "已建立动态画像" : "等待画像输入"}</strong>
          <p>{latestProfile ? `目标：${latestProfile.goal || "等待补充"}；基础：${profileLevelLabel(latestProfile.level)}。` : "画像会随对话、资源学习、答疑和测验结果持续更新。"}</p>
        </article>
      </section>

      <section className="dashboard-recommendation">
        <div>
          <p className="eyebrow">下一步推荐</p>
          <h3>{nextStepTitle(flow, latestProfile, selectedItem)}</h3>
          <p>{nextStepDetail(flow, latestProfile, selectedItem)}</p>
        </div>
        <span>{flow ? "路径推进" : latestProfile ? "路径规划" : "画像构建"}</span>
      </section>

      <div className="agent-system-overview">
        <MultiAgentOverview activeStep="home" />
      </div>
    </section>
  );
}

function profileLevelLabel(level: string): string {
  const labels: Record<string, string> = {
    beginner: "基础入门",
    intermediate: "进阶理解",
    advanced: "高阶提升"
  };
  return labels[level] ?? level;
}

function nextStepTitle(flow: LearningFlow | null, latestProfile: StudentProfile | null, selectedItem: LearningPathItem | null): string {
  if (flow) return selectedItem?.title ?? "继续当前学习节点";
  if (latestProfile) return "生成个性化学习路径";
  return "完成对话式学生画像";
}

function nextStepDetail(flow: LearningFlow | null, latestProfile: StudentProfile | null, selectedItem: LearningPathItem | null): string {
  if (flow) return selectedItem?.success_criterion ?? "围绕当前节点生成资料、完成练习并进行学习效果评估。";
  if (latestProfile) return "画像已经可用，建议进入学习路径模块生成按顺序推进的学习计划。";
  return "先用自然语言说明课程、目标、基础水平和学习偏好，系统会自动抽取画像维度。";
}
