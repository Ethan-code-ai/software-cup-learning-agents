import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import rehypeKatex from "rehype-katex";
import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";

export function SafetyStatusBanner({
  status,
  message
}: {
  status?: "passed" | "blocked" | "degraded";
  message?: string | null;
}) {
  if (!status || status === "passed") return null;
  const fallback = status === "blocked"
    ? "安全策略已拦截该请求，未调用检索或大模型。"
    : "已安全降级；课程资料不足或生成内容未通过安全校验。";
  return (
    <p className={`safety-status safety-status-${status}`} data-testid="safety-status" role="status">
      {message || fallback}
    </p>
  );
}


export function MarkdownBlock({ text }: { text: string }) {
  return (
    <div className="markdown-body" data-testid="markdown-body">
      <ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>{text}</ReactMarkdown>
    </div>
  );
}


export function TypewriterMarkdown({ text }: { text: string }) {
  const [visibleText, setVisibleText] = useState("");

  useEffect(() => {
    setVisibleText("");
    if (!text) return;
    let index = 0;
    const timer = window.setInterval(() => {
      index += Math.max(1, Math.ceil(text.length / 120));
      setVisibleText(text.slice(0, index));
      if (index >= text.length) window.clearInterval(timer);
    }, 18);
    return () => window.clearInterval(timer);
  }, [text]);

  return <MarkdownBlock text={visibleText || " "} />;
}


export function Panel({ title, kicker, children }: { title: string; kicker: string; children: ReactNode }) {
  return (
    <section className="panel">
      <p className="eyebrow">{kicker}</p>
      <h2>{title}</h2>
      <div className="panel-body">{children}</div>
    </section>
  );
}


export function Metric({ label, value, dark = false }: { label: string; value: string; dark?: boolean }) {
  return (
    <div className={`metric ${dark ? "metric-dark" : ""}`}>
      <p>{label}</p>
      <strong>{value}</strong>
    </div>
  );
}


export function EmptyState({ text }: { text: string }) {
  return <p className="empty-state">{text}</p>;
}


export function StatusLine({ busy, error }: { busy: boolean; error: string | null }) {
  if (busy) return <p className="status-line">正在加载初始数据...</p>;
  if (error) return <p className="error-note">{error}</p>;
  return null;
}

type TrackerStep = {
  label: string;
  detail: string;
  status: "done" | "active" | "pending";
};

export function DebugModal(props: {
  open: boolean;
  busy: string | null;
  booting: boolean;
  error: string | null;
  onClose: () => void;
  onLoadDemo: () => void;
  onResetDemo: () => void;
}) {
  if (!props.open) return null;

  return (
    <div className="modal-overlay">
      <button className="modal-backdrop" aria-label="关闭设置与调试" onClick={props.onClose} />
      <section className="modal-card" role="dialog" aria-modal="true" aria-label="设置与调试">
        <div className="modal-header">
          <div>
            <p className="eyebrow">设置 / 调试</p>
            <h2>演示数据控制</h2>
          </div>
          <button className="icon-button" type="button" aria-label="关闭设置与调试" onClick={props.onClose}>
            ×
          </button>
        </div>
        <div className="modal-body">
          <button
            className="action-button w-full"
            data-testid="load-demo-button"
            disabled={props.busy !== null}
            onClick={props.onLoadDemo}
          >
            {props.busy === "load-demo" ? "正在加载演示数据" : "加载或刷新演示数据"}
          </button>
          <button
            className="danger-button w-full"
            data-testid="reset-demo-button"
            disabled={props.busy !== null}
            onClick={props.onResetDemo}
          >
            {props.busy === "reset-demo" ? "正在重置" : "重置用户演示数据"}
          </button>
          <StatusLine busy={props.booting} error={props.error} />
        </div>
      </section>
    </div>
  );
}


export function AgentLoading({ testId, title, detail }: { testId: string; title: string; detail: string }) {
  return (
    <div className="agent-loading" data-testid={testId} aria-live="polite">
      <span className="agent-loading-dot" />
      <div>
        <p>{title}</p>
        <span>{detail}</span>
      </div>
    </div>
  );
}


export function StatusTracker({ testId, steps, compact = false }: { testId: string; steps: TrackerStep[]; compact?: boolean }) {
  return (
    <div className={`status-tracker ${compact ? "status-tracker-compact" : ""}`} data-testid={testId} aria-live="polite">
      {steps.map((step) => (
        <div key={step.label} className={`tracker-step tracker-${step.status}`}>
          <span className="tracker-node">{step.status === "done" ? "✓" : step.status === "active" ? "⚙" : "✨"}</span>
          <div>
            <strong>{step.label}</strong>
            <p>{step.detail}</p>
          </div>
        </div>
      ))}
    </div>
  );
}

