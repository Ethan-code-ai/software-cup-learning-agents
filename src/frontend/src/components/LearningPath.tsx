import type { Concept, LearningPath, LearningPathItem } from "../api/types";
import { EmptyState } from "./common";

export function PathIntentSummary({ path, concepts }: { path: LearningPath | null; concepts: Concept[] }) {
  if (!path) return null;
  const namesById = new Map(concepts.map((concept) => [concept.id, concept.name]));
  const targetNames = (path.target_concept_ids ?? [])
    .map((conceptId) => namesById.get(conceptId))
    .filter((name): name is string => Boolean(name));
  const prerequisiteItems = path.items.filter((item) => item.node_role === "prerequisite");
  const targetItems = path.items.filter((item) => item.node_role === "target");
  const totalMinutes = path.items.reduce((total, item) => total + item.estimated_minutes, 0)
    + (path.milestones ?? []).reduce((total, item) => total + item.estimated_minutes, 0);
  const completedCount = path.items.filter((item) => item.status === "completed").length;

  return (
    <section className="path-intent-summary" data-testid="path-intent-summary" aria-label="本次学习路径摘要">
      <header>
        <div>
          <span>本次重点</span>
          <strong>{targetNames.join("、") || "等待识别目标知识点"}</strong>
        </div>
        <div className="path-intent-meta">
          <span>{purposeLabel(String(path.learning_intent?.purpose ?? "concept_learning"))}</span>
          <span>预计 {totalMinutes} 分钟</span>
          <span>完成 {completedCount}/{path.items.length}</span>
        </div>
      </header>
      <div className="path-phase-summary">
        <article>
          <span>01 基础检查</span>
          <strong>{prerequisiteItems.length} 个前置节点</strong>
          <small>用于快速补齐先修概念，避免直接进入高难内容。</small>
        </article>
        <article className="path-phase-focus">
          <span>02 重点巩固</span>
          <strong>{targetItems.length} 个目标节点</strong>
          <small>围绕核心知识点生成资料、练习和答疑内容。</small>
        </article>
        <article>
          <span>03 效果评估</span>
          <strong>{path.milestones?.length ? "含综合测验" : "按节点检测"}</strong>
          <small>{path.milestones?.[0]?.success_criterion ?? "完成目标节点后进行掌握度检测。"}</small>
        </article>
      </div>
      {path.fallback_used ? <p className="path-fallback-note">智能规划暂时降级，系统仍保留学习重点、时间分配和检测节点。</p> : null}
    </section>
  );
}

export function PathTimeline({
  items,
  concepts,
  selectedId,
  onSelect
}: {
  items: LearningPathItem[];
  concepts: Concept[];
  selectedId: number | null;
  onSelect: (item: LearningPathItem) => void;
}) {
  if (items.length === 0) return <EmptyState text="生成学习路径后，这里会展示按顺序排列的学习节点。" />;
  return (
    <nav className="path-timeline" data-testid="path-timeline" aria-label="学习路径节点">
      {items.map((item) => (
        <PathItemCard
          key={item.id}
          item={item}
          concept={concepts.find((concept) => concept.id === item.concept_id) ?? null}
          selected={item.id === selectedId}
          onSelect={() => onSelect(item)}
        />
      ))}
    </nav>
  );
}

export function PathItemCard({ item, concept, selected, onSelect }: { item: LearningPathItem; concept: Concept | null; selected: boolean; onSelect: () => void }) {
  return (
    <button
      className={`path-card path-card-${item.node_role} path-card-${item.status} ${selected ? "path-card-active" : ""}`}
      data-testid="path-item-card"
      type="button"
      aria-current={selected ? "step" : undefined}
      onClick={onSelect}
    >
      <span className="path-step-index" aria-hidden="true">
        {item.status === "completed" ? "✓" : String(item.order_index).padStart(2, "0")}
      </span>
      <div className="path-card-main">
        <div className="path-card-title-row">
          <strong>{item.title}</strong>
          <em>{statusLabel(item.status)}</em>
        </div>
        <p>{item.objective}</p>
        <small>{concept?.name ?? `概念 ${item.concept_id}`} · {activityTypeLabel(item.activity_type)} · {item.estimated_minutes} 分钟</small>
      </div>
    </button>
  );
}

export function PersistentLearningPathRail({
  items,
  concepts,
  selectedId,
  onSelect,
  onOpenPath,
  busy,
  onCompleteCurrent
}: {
  items: LearningPathItem[];
  concepts: Concept[];
  selectedId: number | null;
  onSelect: (item: LearningPathItem) => void;
  onOpenPath: () => void;
  busy: boolean;
  onCompleteCurrent: () => void;
}) {
  const completedCount = items.filter((item) => item.status === "completed").length;
  const selectedItem = items.find((item) => item.id === selectedId) ?? items[0] ?? null;
  const selectedItemComplete = selectedItem?.status === "completed";

  return (
    <aside className="learning-path-rail" data-testid="persistent-path-rail" aria-label="常驻学习路径">
      <header className="learning-path-rail-header">
        <div>
          <p className="eyebrow">学习路径</p>
          <h2>按节点推进</h2>
          <span>{items.length ? `已完成 ${completedCount}/${items.length} 个节点` : "生成后可在这里切换节点"}</span>
        </div>
        <button className="rail-manage-button" type="button" onClick={onOpenPath}>
          {items.length ? "管理" : "规划"}
        </button>
      </header>
      <PathTimeline items={items} concepts={concepts} selectedId={selectedId} onSelect={onSelect} />
      <footer className="learning-path-rail-action">
        <div>
          <span>当前节点</span>
          <strong>{selectedItem?.title ?? "尚未生成学习路径"}</strong>
        </div>
        <button
          className="primary-button"
          data-testid="complete-path-item-rail-button"
          type="button"
          disabled={!selectedItem || selectedItemComplete || busy}
          onClick={onCompleteCurrent}
        >
          {selectedItemComplete ? "当前节点已完成" : busy ? "正在更新节点" : "完成当前节点学习"}
        </button>
      </footer>
    </aside>
  );
}

export function NodeSummary({ item, concept }: { item: LearningPathItem | null; concept: Concept | null }) {
  if (!item) return <EmptyState text="请选择或生成一个学习节点。" />;
  return (
    <div className="node-summary node-summary-commercial" data-testid="current-node">
      <div className="node-summary-head">
        <div>
          <p className="eyebrow">当前节点</p>
          <strong>{item.title}</strong>
        </div>
        <span>{statusLabel(item.status)}</span>
      </div>
      <p>{item.objective}</p>
      <div className="node-facts">
        <span>{item.node_role === "target" ? "目标节点" : "基础节点"}</span>
        <span>{activityTypeLabel(item.activity_type)}</span>
        <span>{item.estimated_minutes} 分钟</span>
      </div>
      <section className="completion-rule">
        <span>完成条件</span>
        <p>{item.success_criterion}</p>
      </section>
      {item.recommended_resource_type ? (
        <section className="completion-rule">
          <span>推荐资源</span>
          <p>{resourceTypeLabel(item.recommended_resource_type)}</p>
        </section>
      ) : null}
      {item.recommendation_reason ? <small>{item.recommendation_reason}</small> : null}
      <small>{concept?.name ?? `概念 ${item.concept_id}`}</small>
    </div>
  );
}

export function NodeCompletionPanel({ item }: { item: LearningPathItem | null }) {
  if (!item) return null;
  const complete = item.status === "completed";
  return (
    <aside className="node-completion-panel">
      <p className="eyebrow">掌握检查</p>
      <strong>{complete ? "当前节点已完成" : "完成前建议确认"}</strong>
      <ul>
        <li>已阅读或生成当前节点的学习资源</li>
        <li>能用自己的话复述核心概念</li>
        <li>完成至少一次练习或测验反馈</li>
      </ul>
      <small>点击完成后，系统会记录进度，并用于后续画像更新和路径调整。</small>
    </aside>
  );
}

export function CurrentLearningAnchor({
  item,
  concept,
  items,
  onSelectItem,
  onOpenPath
}: {
  item: LearningPathItem | null;
  concept: Concept | null;
  items: LearningPathItem[];
  onSelectItem: (item: LearningPathItem) => void;
  onOpenPath: () => void;
}) {
  if (!item) {
    return (
      <section className="current-learning-anchor current-learning-anchor-empty" aria-label="当前学习节点">
        <div>
          <span className="anchor-label">当前学习计划</span>
          <strong>还没有生成学习路径</strong>
          <p>先完成学生画像并生成学习路径，后续资源、答疑和测验都会围绕当前节点展开。</p>
        </div>
        <button className="small-button" type="button" onClick={onOpenPath}>
          去生成路径
        </button>
      </section>
    );
  }

  const currentIndex = items.findIndex((candidate) => candidate.id === item.id);
  const previousItem = currentIndex > 0 ? items[currentIndex - 1] : null;
  const nextItem = currentIndex >= 0 && currentIndex < items.length - 1 ? items[currentIndex + 1] : null;
  const completedCount = items.filter((candidate) => candidate.status === "completed").length;
  const progress = items.length ? Math.round((completedCount / items.length) * 100) : 0;

  return (
    <section className="current-learning-anchor" aria-label="当前学习节点">
      <div className="anchor-main">
        <div className="anchor-title-row">
          <span className="anchor-label">当前学习节点</span>
          <em>{statusLabel(item.status)}</em>
        </div>
        <strong>{item.title}</strong>
        <p>{item.objective}</p>
        <div className="anchor-meta">
          <span>{concept?.name ?? `课程概念 ${item.concept_id}`}</span>
          <span>{activityTypeLabel(item.activity_type)}</span>
          <span>{item.estimated_minutes} 分钟</span>
          <span>进度 {completedCount}/{items.length}</span>
        </div>
        <div className="anchor-progress" aria-hidden="true">
          <i style={{ width: `${progress}%` }} />
        </div>
      </div>
      <div className="anchor-actions">
        <button className="ghost-button" type="button" disabled={!previousItem} onClick={() => previousItem && onSelectItem(previousItem)}>
          上一步
        </button>
        <button className="ghost-button" type="button" disabled={!nextItem} onClick={() => nextItem && onSelectItem(nextItem)}>
          下一步
        </button>
        <button className="small-button" type="button" onClick={onOpenPath}>
          查看完整路径
        </button>
      </div>
    </section>
  );
}

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    completed: "已完成",
    active: "进行中",
    pending: "待学习"
  };
  return labels[status] ?? "待学习";
}

function purposeLabel(purpose: string): string {
  const labels: Record<string, string> = {
    assessment_preparation: "课程小测准备",
    concept_learning: "概念学习",
    project_application: "项目实践",
    interview_preparation: "面试准备",
    skill_consolidation: "知识巩固"
  };
  return labels[purpose] ?? "个性化学习";
}

export function resourceTypeLabel(resourceType: string) {
  const labels: Record<string, string> = {
    guided_note: "讲解文档",
    practice_questions: "练习题库",
    mind_map: "思维导图",
    extended_reading: "拓展阅读",
    coding_case: "代码实操案例",
    teaching_video: "教学动画"
  };
  return labels[resourceType] ?? resourceType;
}

export function activityTypeLabel(activityType: string) {
  const labels: Record<string, string> = {
    explanation: "概念讲解",
    concept_comparison: "概念对比",
    worked_example: "典型例题",
    coding: "代码实践",
    error_review: "易错点复盘",
    mock_assessment: "模拟测验",
    visual_map: "思维导图"
  };
  return labels[activityType] ?? activityType;
}
