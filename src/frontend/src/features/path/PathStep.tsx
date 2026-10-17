import type { AgentRun, ConceptGraph, LearningFlow, LearningPathItem } from "../../api/types";
import { InlineAgentTrace } from "../../components/AgentTrace";
import { AgentLoading } from "../../components/common";
import { NodeCompletionPanel, NodeSummary, PathIntentSummary, PathTimeline } from "../../components/LearningPath";

type BusyAction = string | null;

const goalExamples = [
  "我想在 2 小时内掌握二叉树遍历，并能独立完成递归与非递归题目",
  "期末前复习图搜索、最短路径和拓扑排序，重点解决易混淆点",
  "为数据结构小测做准备，先补栈、队列、树和 BFS/DFS 的基础"
];

export default function PathStep({
  goal,
  onGoalChange,
  canCreatePath,
  busy,
  error,
  runs,
  traceVisible,
  flow,
  graph,
  pathItems,
  selectedItem,
  selectedConcept,
  onCreatePath,
  onSelectPathItem,
  onCompleteItem
}: {
  goal: string;
  onGoalChange: (value: string) => void;
  canCreatePath: boolean;
  busy: BusyAction;
  error: string | null;
  runs: AgentRun[];
  traceVisible: boolean;
  flow: LearningFlow | null;
  graph: ConceptGraph | null;
  pathItems: LearningPathItem[];
  selectedItem: LearningPathItem | null;
  selectedConcept: ConceptGraph["concepts"][number] | null;
  onCreatePath: () => void;
  onSelectPathItem: (item: LearningPathItem) => void;
  onCompleteItem: () => void;
}) {
  return (
    <div className="path-workspace">
      <section className="path-command-panel">
        <div className="path-command-copy">
          <p className="eyebrow">学习规划师</p>
          <h2>生成可执行的个性化学习路径</h2>
          <p>
            这里不建议只填一个关键词。更好的写法是“学习目标 + 时间约束 + 薄弱点或考试目标”，系统会结合学生画像和知识库拆成可执行节点。
          </p>
        </div>
        <div className="path-command-form">
          <input
            className="field"
            value={goal}
            onChange={(event) => onGoalChange(event.target.value)}
            aria-label="学习目标"
            placeholder="例如：我想复习二叉树、图搜索和复杂度分析，2 小时内完成并通过小测"
          />
          <div className="path-goal-examples">
            {goalExamples.map((example) => (
              <button key={example} type="button" onClick={() => onGoalChange(example)}>
                {example}
              </button>
            ))}
          </div>
          <button className="primary-button" data-testid="create-path-button" disabled={!canCreatePath || busy !== null} onClick={onCreatePath}>
            {busy === "create-path" ? "正在规划路径" : "生成学习路径"}
          </button>
        </div>
      </section>

      {error ? (
        <p className="error-note" role="alert">
          {error}
        </p>
      ) : null}
      {busy === "create-path" ? (
        <AgentLoading
          testId="planner-loading"
          title="学习规划师正在编排路径"
          detail="系统正在结合画像、课程图谱和学习目标排序。"
        />
      ) : null}
      <InlineAgentTrace action="path" busy={busy === "create-path"} runs={runs} visible={traceVisible} />
      <PathIntentSummary path={flow?.learning_path ?? null} concepts={graph?.concepts ?? []} />

      <div className="path-detail-layout">
        <section className="path-timeline-panel" data-testid="path-timeline-main">
          <div className="section-heading">
            <div>
              <p className="eyebrow">学习时间线</p>
              <h2>按顺序推进的学习节点</h2>
            </div>
          </div>
          <PathTimeline items={pathItems} concepts={graph?.concepts ?? []} selectedId={selectedItem?.id ?? null} onSelect={onSelectPathItem} />
        </section>

        <section className="path-current-panel">
          <NodeSummary item={selectedItem} concept={selectedConcept} />
          <NodeCompletionPanel item={selectedItem} />
          {selectedItem ? (
            <button
              className="primary-button w-full"
              data-testid="complete-path-item-button"
              disabled={selectedItem.status === "completed" || busy !== null}
              onClick={onCompleteItem}
            >
              {selectedItem.status === "completed"
                ? "当前节点已完成"
                : busy === "complete-path-item"
                  ? "正在提交学习结果"
                  : "提交本节点学习结果"}
            </button>
          ) : null}
        </section>
      </div>

      {flow?.learning_path.milestones?.map((milestone) => (
        <article className="path-milestone-card" data-testid="path-milestone" key={`${milestone.milestone_type}-${milestone.title}`}>
          <div>
            <span>综合检测 · {milestone.estimated_minutes} 分钟</span>
            <strong>{milestone.title}</strong>
          </div>
          <p>{milestone.objective}</p>
          <small>完成标准：{milestone.success_criterion}</small>
        </article>
      ))}
    </div>
  );
}
