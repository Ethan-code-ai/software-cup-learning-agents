import type { AnimationNode, AnimationSpec, AnimationTimelineStep } from "../../api/types";

export default function AnimationScene({
  spec,
  step,
  completedTargets,
}: {
  spec: AnimationSpec;
  step: AnimationTimelineStep | null;
  completedTargets: string[];
}) {
  const nodeMap = new Map(spec.data.nodes.map((node) => [node.id, node]));
  const isBarScene = spec.template_id === "complexity_visualizer" || spec.template_id === "sorting_visualizer";
  const isBoxScene = ["linear_structure", "stack_queue_operations", "search_visualizer", "algorithm_workflow"].includes(spec.template_id);
  const isMutableStructure = spec.template_id === "stack_queue_operations" && Boolean(step?.frontier.length);

  function nodeClass(node: AnimationNode, index: number): string {
    const outsideRange = step?.range_start !== null && step?.range_start !== undefined
      && step?.range_end !== null && step?.range_end !== undefined
      && (index < step.range_start || index > step.range_end);
    return [
      "animation-node",
      completedTargets.includes(node.id) ? "animation-node-visited" : "",
      step?.target === node.id ? "animation-node-current" : "",
      outsideRange ? "animation-node-muted" : "",
    ].filter(Boolean).join(" ");
  }

  function mutablePosition(node: AnimationNode): { x: number; y: number } {
    const index = step?.frontier.indexOf(node.id) ?? -1;
    if (spec.data.mode === "queue") return { x: 150 + index * 115, y: 172 };
    return { x: 320, y: 270 - index * 62 };
  }

  return (
    <svg viewBox="0 0 640 330" role="img" aria-label={`${spec.title}动画`} data-testid="animation-scene">
      <defs>
        <marker id="animation-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
          <path d="M0,0 L8,4 L0,8 Z" />
        </marker>
      </defs>
      <g className="animation-edges" aria-hidden="true">
        {spec.data.edges.map((edge) => {
          const source = nodeMap.get(edge.source);
          const target = nodeMap.get(edge.target);
          if (!source || !target) return null;
          return (
            <g key={`${edge.source}-${edge.target}`}>
              <line x1={source.x} y1={source.y} x2={target.x} y2={target.y} markerEnd="url(#animation-arrow)" />
              {edge.label ? <text x={(source.x + target.x) / 2} y={(source.y + target.y) / 2 - 8}>{edge.label}</text> : null}
            </g>
          );
        })}
      </g>
      {spec.template_id === "stack_queue_operations" ? (
        <g className="animation-structure-guide" aria-hidden="true">
          {spec.data.mode === "queue" ? (
            <>
              <path d="M92 122 H548 M92 222 H548" />
              <text x="92" y="104">Front · 出队</text>
              <text x="548" y="104" textAnchor="end">Rear · 入队</text>
            </>
          ) : (
            <>
              <path d="M258 34 V304 H382 V34" />
              <text x="397" y="54">Top · push / pop</text>
            </>
          )}
        </g>
      ) : null}
      <g className={`animation-nodes animation-scene-${spec.template_id}`}>
        {spec.data.nodes.map((node, index) => {
          if (isMutableStructure && !step?.frontier.includes(node.id)) return null;
          const className = nodeClass(node, index);
          const label = step?.labels[node.id] ?? node.label;
          if (isBarScene) {
            const value = step?.values[node.id] ?? node.value ?? 20;
            const height = Math.min(250, Math.max(42, value * 1.6));
            return (
              <g key={node.id} className={`${className} animation-bar`} transform={`translate(${node.x} 300)`} data-node-id={node.id}>
                <rect x="-34" y={-height} width="68" height={height} rx="8" />
                <text textAnchor="middle" y={-height - 12}>{spec.template_id === "sorting_visualizer" ? value : label}</text>
              </g>
            );
          }
          if (isBoxScene) {
            const width = spec.template_id === "algorithm_workflow" ? 112 : 88;
            const position = isMutableStructure ? mutablePosition(node) : node;
            return (
              <g key={node.id} className={`${className} animation-box`} transform={`translate(${position.x} ${position.y})`} data-node-id={node.id}>
                <rect x={-width / 2} y="-27" width={width} height="54" rx="9" />
                <text textAnchor="middle" dominantBaseline="central">{label}</text>
              </g>
            );
          }
          const stateValue = step?.values[node.id];
          return (
            <g key={node.id} className={className} transform={`translate(${node.x} ${node.y})`} data-node-id={node.id}>
              <circle r={node.kind === "focus" ? 42 : 28} />
              <text textAnchor="middle" dominantBaseline="central">{label}</text>
              {stateValue !== undefined ? <text className="animation-node-state" textAnchor="middle" y="48">{stateValue >= 99 ? "∞" : stateValue}</text> : null}
            </g>
          );
        })}
      </g>
    </svg>
  );
}
