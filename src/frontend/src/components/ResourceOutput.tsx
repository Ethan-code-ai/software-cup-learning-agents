import { useMemo, useState } from "react";
import type { GeneratedResource } from "../api/types";
import { MarkdownBlock, SafetyStatusBanner, TypewriterMarkdown } from "./common";
import AnimationRenderer from "./animation/AnimationRenderer";

type MindMapBranch = {
  title: string;
  children: string[];
};

type ParsedMindMap = {
  center: string;
  branches: MindMapBranch[];
};

function formatScore(value: unknown): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "暂无";
  return value.toFixed(2);
}

function formatList(value: unknown): string {
  if (!Array.isArray(value) || value.length === 0) return "暂无";
  return value.map((item) => String(item)).join("、");
}

function resourceLabel(type: string): string {
  const labels: Record<string, string> = {
    guided_note: "讲解文档",
    practice_questions: "练习题库",
    mind_map: "思维导图",
    extended_reading: "拓展阅读",
    coding_case: "代码实操",
    teaching_video: "教学动画"
  };
  return labels[type] ?? type;
}

export default function ResourceOutputBlock({ resource }: { resource: GeneratedResource }) {
  return (
    <article className="resource-card" data-testid="output-block">
      <ResourceHeader title={resourceLabel(resource.resource_type)} />
      <SafetyStatusBanner status={resource.safety_status} message={resource.safety_message} />
      {resource.resource_type === "teaching_video" && resource.animation_spec ? <AnimationRenderer spec={resource.animation_spec} /> : null}
      {resource.resource_type === "teaching_video" && !resource.animation_spec ? <LegacyAnimationNotice /> : null}
      {resource.resource_type === "mind_map" ? <MindMapDiagram text={resource.content} /> : null}
      {resource.resource_type === "coding_case" ? <CodeCaseCard code={extractFencedCode(resource.content) || resource.content} /> : null}
      {resource.resource_type !== "mind_map" && resource.resource_type !== "coding_case" && resource.resource_type !== "teaching_video" ? <TypewriterMarkdown text={resource.content} /> : null}
      {resource.resource_type === "teaching_video" ? <VideoScriptBlock text={resource.content} /> : null}
      <SourceEvidence sourceRefs={resource.source_refs} />
    </article>
  );
}

function LegacyAnimationNotice() {
  return (
    <article className="animation-legacy-notice" role="status" data-testid="animation-legacy-notice">
      <strong>这是一条旧版动画资源</strong>
      <span>旧记录未包含动画场景数据，请点击左侧“生成教学动画”重新生成。</span>
    </article>
  );
}

function VideoScriptBlock({ text }: { text: string }) {
  return (
    <div className="video-script-block">
      <p className="eyebrow">动画脚本 / 分镜说明</p>
      <TypewriterMarkdown text={text} />
    </div>
  );
}

function CodeCaseCard({ code }: { code: string }) {
  const [tab, setTab] = useState<"code" | "output">("code");
  const [copied, setCopied] = useState(false);

  async function copyCode() {
    try {
      await navigator.clipboard?.writeText(code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      setCopied(false);
    }
  }

  return (
    <article className="code-case-card" data-testid="coding-case-card">
      <div className="code-case-toolbar">
        <div className="window-dots" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
        <div className="code-tabs">
          <button className={tab === "code" ? "code-tab-active" : ""} type="button" onClick={() => setTab("code")}>代码</button>
          <button className={tab === "output" ? "code-tab-active" : ""} type="button" onClick={() => setTab("output")}>运行输出</button>
        </div>
        <button className="copy-button" type="button" onClick={() => void copyCode()}>
          {copied ? "已复制" : "复制"}
        </button>
      </div>
      {tab === "code" ? (
        <pre className="code-case-block">{code}</pre>
      ) : (
        <div className="run-output-placeholder">
          <strong>运行输出预览</strong>
          <p>接入在线沙箱后，这里会展示测试结果、复杂度分析与调试建议。</p>
        </div>
      )}
    </article>
  );
}

export function OutputBlock({ title, text, sourceRefs }: { title: string; text: string; sourceRefs: Array<Record<string, unknown>> }) {
  return (
    <article className="resource-card" data-testid="output-block">
      <ResourceHeader title={title} />
      <MarkdownBlock text={text} />
      <SourceEvidence sourceRefs={sourceRefs} />
    </article>
  );
}

function MindMapDiagram({ text }: { text: string }) {
  const mindMap = useMemo(() => parseMindMap(text), [text]);
  const leftBranches = mindMap.branches.filter((_, index) => index % 2 === 0);
  const rightBranches = mindMap.branches.filter((_, index) => index % 2 === 1);
  const maxSideCount = Math.max(leftBranches.length, rightBranches.length, 2);
  const canvasHeight = Math.max(430, maxSideCount * 126);

  return (
    <div className="mind-map-diagram" data-testid="mind-map-card">
      <div className="mind-map-toolbar">
        <span>结构化导图</span>
        <small>{mindMap.branches.length} 个分支</small>
      </div>
      <div className="mind-map-canvas" style={{ minHeight: `${canvasHeight}px` }}>
        <svg className="mind-map-lines" viewBox={`0 0 1000 ${canvasHeight}`} preserveAspectRatio="none" aria-hidden="true">
          {leftBranches.map((_, index) => {
            const y = branchY(index, leftBranches.length, canvasHeight);
            return <path key={`left-${index}`} d={`M 500 ${canvasHeight / 2} C 390 ${canvasHeight / 2}, 330 ${y}, 230 ${y}`} />;
          })}
          {rightBranches.map((_, index) => {
            const y = branchY(index, rightBranches.length, canvasHeight);
            return <path key={`right-${index}`} d={`M 500 ${canvasHeight / 2} C 610 ${canvasHeight / 2}, 670 ${y}, 770 ${y}`} />;
          })}
        </svg>

        <div className="mind-map-center-node" style={{ top: `${canvasHeight / 2}px` }}>
          <span>中心主题</span>
          <strong>{mindMap.center}</strong>
        </div>

        <div className="mind-map-side mind-map-side-left">
          {leftBranches.map((branch, index) => (
            <MindMapNode key={`${branch.title}-${index}`} branch={branch} top={branchY(index, leftBranches.length, canvasHeight)} />
          ))}
        </div>
        <div className="mind-map-side mind-map-side-right">
          {rightBranches.map((branch, index) => (
            <MindMapNode key={`${branch.title}-${index}`} branch={branch} top={branchY(index, rightBranches.length, canvasHeight)} />
          ))}
        </div>
      </div>
    </div>
  );
}

function MindMapNode({ branch, top }: { branch: MindMapBranch; top: number }) {
  return (
    <article className="mind-map-node" style={{ top: `${top}px` }}>
      <strong>{branch.title}</strong>
      {branch.children.length > 0 ? (
        <ul>
          {branch.children.slice(0, 3).map((child, index) => (
            <li key={`${child}-${index}`}>{child}</li>
          ))}
        </ul>
      ) : null}
    </article>
  );
}

function branchY(index: number, count: number, height: number): number {
  if (count <= 1) return height / 2;
  const padding = 82;
  return padding + (index * (height - padding * 2)) / (count - 1);
}

function parseMindMap(text: string): ParsedMindMap {
  const cleaned = text.replace(/```[\s\S]*?```/g, "");
  const lines = cleaned.split("\n").filter((line) => line.trim().length > 0);
  const titleLine = lines.find((line) => /^#{1,3}\s+/.test(line.trim()) || /^【.+】/.test(line.trim()))?.trim();
  let center = stripDecorations(titleLine ?? "知识主题").replace(/^思维导图[：:\s-]*/, "") || "知识主题";
  const branches: MindMapBranch[] = [];
  let currentBranch: MindMapBranch | null = null;
  let centerBulletSeen = false;

  for (const rawLine of lines) {
    const plainLine = stripDecorations(rawLine.trim());
    const plainCenterMatch = plainLine.match(/^中心主题[：:]\s*(.+)$/);
    if (plainCenterMatch?.[1]) {
      center = stripDecorations(plainCenterMatch[1]);
      centerBulletSeen = false;
      currentBranch = null;
      continue;
    }

    const branchMatch = plainLine.match(/^分支[：:]\s*(.+)$/);
    if (branchMatch?.[1]) {
      const parsed = parseBranchLine(branchMatch[1]);
      currentBranch = parsed;
      branches.push(currentBranch);
      centerBulletSeen = false;
      continue;
    }

    const bullet = rawLine.match(/^(\s*)[-*+]\s+(.+)$/);
    const heading = rawLine.trim().match(/^(#{2,5})\s+(.+)$/);
    const rawText = bullet?.[2] ?? heading?.[2] ?? "";
    if (!rawText) continue;

    const itemText = stripDecorations(rawText);
    if (!itemText || itemText === center) continue;

    const centerMatch = itemText.match(/^中心主题[：:]\s*(.+)$/);
    if (centerMatch?.[1]) {
      center = stripDecorations(centerMatch[1]);
      centerBulletSeen = true;
      currentBranch = null;
      continue;
    }

    const indent = bullet ? bullet[1].replace(/\t/g, "  ").length : 0;
    const level = heading ? heading[1].length - 1 : Math.floor(indent / 2) + 1;
    const shouldBeBranch = level <= 1 || centerBulletSeen;

    if (shouldBeBranch) {
      currentBranch = { title: itemText, children: [] };
      branches.push(currentBranch);
      centerBulletSeen = false;
    } else if (currentBranch) {
      currentBranch.children.push(itemText);
    } else {
      currentBranch = { title: itemText, children: [] };
      branches.push(currentBranch);
    }
  }

  const normalizedBranches = branches
    .map((branch) => ({
      title: shorten(stripPrefixLabel(branch.title), 34),
      children: branch.children.map((child) => shorten(stripPrefixLabel(child), 46)).filter(Boolean)
    }))
    .filter((branch) => branch.title.length > 0)
    .slice(0, 8);

  if (normalizedBranches.length === 0) {
    return {
      center: shorten(center, 30),
      branches: [
        { title: "核心概念", children: ["提炼定义、符号和适用条件"] },
        { title: "学习目标", children: ["明确当前节点要掌握的能力"] },
        { title: "易错提醒", children: ["记录常见混淆点和反例"] },
        { title: "练习路径", children: ["复述概念、对比场景、完成小测"] }
      ]
    };
  }

  return { center: shorten(center, 30), branches: normalizedBranches };
}

function stripDecorations(value: string): string {
  return value
    .replace(/^#{1,6}\s*/, "")
    .replace(/^【[^】]+】\s*/, "")
    .replace(/\[[0-9,\s]+\]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function stripPrefixLabel(value: string): string {
  return value.replace(/^(分支|要点|节点|主题|学习目标|资料依据|画像侧重点|易错点|练习路径)[：:]\s*/, "").trim();
}

function parseBranchLine(value: string): MindMapBranch {
  const normalized = stripDecorations(value)
    .replace(/\s*[-=]+>\s*/g, " -> ")
    .replace(/\s*→\s*/g, " -> ");
  const parts = normalized.split(" -> ").map((part) => part.trim()).filter(Boolean);
  if (parts.length >= 2) {
    return { title: parts[0], children: splitBranchDetail(parts.slice(1).join(" -> ")) };
  }

  const colonParts = normalized.split(/[：:]/).map((part) => part.trim()).filter(Boolean);
  if (colonParts.length >= 2) {
    return { title: colonParts[0], children: splitBranchDetail(colonParts.slice(1).join("：")) };
  }

  return { title: normalized, children: [] };
}

function splitBranchDetail(value: string): string[] {
  return value
    .split(/[；;。]/)
    .map((item) => stripDecorations(item))
    .filter(Boolean)
    .slice(0, 3);
}

function shorten(value: string, maxLength: number): string {
  return value.length > maxLength ? `${value.slice(0, maxLength - 1)}…` : value;
}

function extractFencedCode(content: string): string {
  const match = content.match(/```(?:python|py|ts|js|tsx|jsx|java|cpp|c)?\s*([\s\S]*?)```/i);
  return match?.[1]?.trim() ?? "";
}

function ResourceHeader({ title }: { title: string }) {
  return (
    <div className="resource-header">
      <h3>{title}</h3>
    </div>
  );
}

export function SourceEvidence({ sourceRefs }: { sourceRefs: Array<Record<string, unknown>> }) {
  const count = Math.min(sourceRefs.length, 5);
  return (
    <details className="source-evidence" data-testid="source-panel">
      <summary>
        <span>
          <strong>生成依据说明</strong>
          <small>说明本资源参考了哪些课程资料摘录，以及为什么可信。</small>
        </span>
        <em>{count ? `${count} 条知识库来源` : "暂无来源"}</em>
      </summary>
      <SourcePanel sourceRefs={sourceRefs} />
    </details>
  );
}

function SourcePanel({ sourceRefs }: { sourceRefs: Array<Record<string, unknown>> }) {
  const visibleSources = sourceRefs.slice(0, 5);
  return (
    <div className="source-panel">
      <div className="source-panel-intro">
        <strong>这些证据从哪里来？</strong>
        <p>
          资源生成前，资料管理员会先从课程知识库查找相关资料摘录；资源设计师只能基于这些摘录组织内容。下面列出本次参考的资料和相关度。
        </p>
      </div>
      {visibleSources.length === 0 ? (
        <p className="source-panel-empty" data-testid="source-empty">暂无来源返回</p>
      ) : (
        <div className="source-panel-list">
          {visibleSources.map((source, index) => (
            <article className="source-detail" data-testid="source-detail" key={`${String(source.source_ref ?? source.chunk_id ?? "source")}-${index}`}>
              <div className="source-detail-header">
                <span>依据 {index + 1}</span>
                <small>相关度 {formatScore(source.rerank_score ?? source.score)}</small>
              </div>
              <strong>{sourceTitle(source)}</strong>
              <p className="source-location">{sourceLocation(source, index)}</p>
              {source.excerpt ? <p className="source-excerpt">{String(source.excerpt)}</p> : null}
              <p className="source-meta">命中词：{formatList(source.matched_terms)} · 锚点：{formatList(source.anchor_matches)}</p>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}

function sourceTitle(source: Record<string, unknown>): string {
  const title = source.source_title ?? source.document_title ?? source.title;
  if (typeof title === "string" && title.trim()) return title.trim();
  return "课程资料摘录";
}

function sourceLocation(source: Record<string, unknown>, index: number): string {
  const parts = [];
  parts.push(`来自课程知识库中与当前主题最相关的第 ${index + 1} 条资料摘录`);
  if (source.retrieval_mode) parts.push(`匹配方式：${retrievalModeLabel(source.retrieval_mode)}`);
  return parts.join(" / ");
}

function retrievalModeLabel(value: unknown): string {
  const mode = String(value || "");
  if (mode === "keyword") return "关键词匹配";
  if (mode === "vector") return "语义向量匹配";
  if (mode === "hybrid") return "关键词 + 语义混合匹配";
  return "知识库检索";
}
