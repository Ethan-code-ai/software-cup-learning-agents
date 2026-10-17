import type { AnimationSpec, AnimationTimelineStep } from "../../api/types";

export default function AnimationStatePanel({
  spec,
  step,
  structureLabel,
}: {
  spec: AnimationSpec;
  step: AnimationTimelineStep | null;
  structureLabel: string;
}) {
  if (!step) return null;
  const labels = new Map(spec.data.nodes.map((node) => [node.id, step.labels[node.id] ?? node.label]));
  const frontierLabels = step.frontier.map((id) => labels.get(id) ?? id);
  const visitedLabels = step.visited.map((id) => labels.get(id) ?? id);
  const orderedValues = spec.data.nodes
    .filter((node) => step.values[node.id] !== undefined)
    .map((node) => step.values[node.id]);
  const isStack = structureLabel.includes("Stack") || structureLabel.includes("栈");
  const isQueue = structureLabel.includes("Queue") || structureLabel.includes("队列");
  const showsFrontier = isStack || isQueue || frontierLabels.length > 0;
  const operationLabels: Partial<Record<AnimationTimelineStep["action"], string>> = {
    push: "push · 压栈",
    pop: "pop · 弹栈",
    enqueue: "enqueue · 入队",
    dequeue: "dequeue · 出队",
  };
  const operationLabel = operationLabels[step.action];

  return (
    <div className="animation-state-panel" data-testid="animation-state-panel" aria-live="polite">
      {operationLabel ? (
        <div className="animation-state-group animation-operation-state">
          <span>当前操作</span>
          <strong data-testid="animation-operation">{operationLabel}</strong>
        </div>
      ) : null}
      {showsFrontier ? (
        <div className="animation-state-group">
          <span>{structureLabel}</span>
          {frontierLabels.length > 0 ? (
            <div className="animation-state-tokens" data-testid="animation-frontier">
              {frontierLabels.map((label, index) => (
                <b key={`${label}-${index}`}>
                  {isQueue && index === 0 ? "Front · " : ""}
                  {label}
                  {isQueue && index === frontierLabels.length - 1 ? " · Rear" : ""}
                  {isStack && index === frontierLabels.length - 1 ? " · Top" : ""}
                </b>
              ))}
            </div>
          ) : <strong data-testid="animation-frontier">空</strong>}
        </div>
      ) : null}
      {visitedLabels.length > 0 ? (
        <div className="animation-state-group">
          <span>已访问 / 已完成</span>
          <strong data-testid="animation-visited">{visitedLabels.join(" → ")}</strong>
        </div>
      ) : null}
      {step.range_start !== null && step.range_end !== null ? (
        <div className="animation-state-group">
          <span>当前查找区间</span>
          <strong data-testid="animation-range">[{step.range_start}, {step.range_end}]</strong>
        </div>
      ) : null}
      {orderedValues.length > 0 && spec.template_id === "sorting_visualizer" ? (
        <div className="animation-state-group">
          <span>当前序列</span>
          <strong data-testid="animation-values">[{orderedValues.join(", ")}]</strong>
        </div>
      ) : null}
    </div>
  );
}
