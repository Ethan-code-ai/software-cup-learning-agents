import type { AgentRun, Concept, GeneratedResource, LearningPathItem } from "../../api/types";
import { InlineAgentTrace } from "../../components/AgentTrace";
import { EmptyState, StatusTracker } from "../../components/common";
import { NodeSummary, resourceTypeLabel } from "../../components/LearningPath";
import ResourceOutputBlock from "../../components/ResourceOutput";

type BusyAction = string | null;

export default function ResourceStep({
  busy,
  selectedItem,
  selectedConcept,
  resource,
  resourceType,
  resourceOptions,
  runs,
  traceVisible,
  learningTraceUpdateNotice,
  onResourceTypeChange,
  onGenerate
}: {
  busy: BusyAction;
  selectedItem: LearningPathItem | null;
  selectedConcept: Concept | null;
  resource: GeneratedResource | null;
  resourceType: string;
  resourceOptions: ReadonlyArray<{ type: string; label: string }>;
  runs: AgentRun[];
  traceVisible: boolean;
  learningTraceUpdateNotice: string | null;
  onResourceTypeChange: (type: string) => void;
  onGenerate: () => void;
}) {
  return (
    <div className="resource-workspace">
      <section className="resource-control-panel">
        <div className="resource-control-head">
          <p className="eyebrow">资源设计师</p>
          <h2>内容生成工作台</h2>
          <p>围绕当前学习节点生成可展示、可追溯、可继续用于测验和答疑的学习资源。</p>
        </div>
        <NodeSummary item={selectedItem} concept={selectedConcept} />
        <div className="resource-type-grid">
          {resourceOptions.map((option) => (
            <button
              key={option.type}
              className={`resource-type-card ${resourceType === option.type ? "resource-type-card-active" : ""}`}
              data-testid={`resource-type-${option.type}`}
              onClick={() => onResourceTypeChange(option.type)}
            >
              <span>{option.label}</span>
              <small>{resourceTypeDescription(option.type)}</small>
            </button>
          ))}
        </div>
        <button className="primary-button w-full" data-testid="generate-resource-button" disabled={!selectedItem || busy !== null} onClick={onGenerate}>
          {busy === "generate-resource" ? "正在生成学习资源" : `生成${resourceTypeLabel(resourceType)}`}
        </button>
        <InlineAgentTrace action="resource" busy={busy === "generate-resource"} runs={runs} visible={traceVisible} />
        {busy === "generate-resource" ? (
          <StatusTracker
            testId="resource-loading"
            steps={[
              { label: "检索课程资料", detail: "资料管理员正在获取相关参考内容", status: "done" },
              { label: "组织资源结构", detail: "资源设计师正在匹配画像与知识短板", status: "active" },
              { label: "校验内容安全", detail: "通过安全校验后展示完整资源", status: "pending" }
            ]}
          />
        ) : null}
        {learningTraceUpdateNotice ? <p className="ai-disclaimer">{learningTraceUpdateNotice}</p> : null}
      </section>

      <section className="resource-preview-panel">
        <div className="resource-preview-head">
          <div>
            <p className="eyebrow">资源预览</p>
            <h2>{resource ? resourceTypeLabel(resource.resource_type) : "等待生成内容"}</h2>
          </div>
          <span>{selectedItem ? selectedItem.title : "未选择节点"}</span>
        </div>
        <div className="resource-preview-body">
          {resource ? <ResourceOutputBlock resource={resource} /> : <EmptyState text="请选择路径节点和资源类型后生成内容。" />}
        </div>
      </section>
    </div>
  );
}

function resourceTypeDescription(type: string): string {
  const descriptions: Record<string, string> = {
    guided_note: "适合系统梳理概念",
    practice_questions: "用于即时检测掌握度",
    mind_map: "适合结构化复盘",
    extended_reading: "补充边界和拓展知识",
    coding_case: "用于代码实践和迁移",
    teaching_video: "生成可交互 SVG 动画和讲解脚本"
  };
  return descriptions[type] ?? "个性化学习资源";
}
