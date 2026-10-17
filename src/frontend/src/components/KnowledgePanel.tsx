import { useState } from "react";

import type {
  DemoDataStatus,
  DocumentIngestionResponse,
  DocumentReindexResponse,
  KnowledgeSearchResult,
  ManagedDocument
} from "../api/types";

type BusyAction =
  | "load-demo"
  | "reset-demo"
  | "build-profile"
  | "delete-profile"
  | "import-knowledge"
  | "upload-knowledge"
  | "refresh-documents"
  | "delete-document"
  | "reindex-document"
  | "search-knowledge"
  | "create-path"
  | "complete-path-item"
  | "generate-resource"
  | "ask-tutor"
  | "generate-quiz"
  | "submit-attempt"
  | "sync-profile";

function formatScore(value: unknown): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "暂无";
  return value.toFixed(2);
}

function documentDisplayName(document: { title: string; file_name?: string | null }): string {
  return document.file_name?.trim() || document.title || "未命名资料";
}

function resultDisplayName(result: KnowledgeSearchResult): string {
  return typeof result.metadata?.document_title === "string" ? result.metadata.document_title : "课程资料摘录";
}

function resultSourceLabel(result: KnowledgeSearchResult, index: number): string {
  const title = resultDisplayName(result);
  const rawMode = (result as KnowledgeSearchResult & { retrieval_mode?: unknown }).retrieval_mode ?? result.metadata?.retrieval_mode;
  const mode = typeof rawMode === "string" ? retrievalModeLabel(rawMode) : "综合匹配";
  return `${title}中的第 ${index + 1} 条相关摘录 / ${mode}`;
}

function retrievalModeLabel(mode: string): string {
  const labels: Record<string, string> = {
    keyword: "关键词匹配",
    vector: "语义匹配",
    hybrid: "综合匹配"
  };
  return labels[mode] ?? "综合匹配";
}

function EmptyState({ text }: { text: string }) {
  return <p className="empty-state">{text}</p>;
}
export default function KnowledgePanel(props: {
  status: DemoDataStatus | null;
  busy: BusyAction | null;
  knowledgeTitle: string;
  setKnowledgeTitle: (value: string) => void;
  knowledgeContent: string;
  setKnowledgeContent: (value: string) => void;
  knowledgeFile: File | null;
  setKnowledgeFile: (value: File | null) => void;
  knowledgeImportResult: DocumentIngestionResponse | null;
  knowledgeReindexResult: DocumentReindexResponse | null;
  knowledgeDocuments: ManagedDocument[];
  knowledgeError: string | null;
  knowledgeQuery: string;
  setKnowledgeQuery: (value: string) => void;
  knowledgeSearchResults: KnowledgeSearchResult[];
  onRunTask: (action: BusyAction, task: () => Promise<void>) => Promise<void>;
  onImport: () => Promise<void>;
  onUpload: () => Promise<void>;
  onSearch: () => Promise<void>;
  onRefresh: () => Promise<void>;
  onDelete: (documentId: number) => Promise<void>;
  onReindex: (documentId: number) => Promise<void>;
}) {
  const [createOpen, setCreateOpen] = useState(false);
  const [showAllDocuments, setShowAllDocuments] = useState(false);
  const visibleDocuments = showAllDocuments ? props.knowledgeDocuments : props.knowledgeDocuments.slice(0, 5);
  const hiddenDocumentCount = Math.max(0, props.knowledgeDocuments.length - visibleDocuments.length);

  return (
    <section className="kb-workspace">
      <aside className="kb-sidebar" data-testid="document-management">
        <div className="kb-sidebar-header">
          <div>
            <p className="eyebrow">资料管理器</p>
            <h2>课程资料</h2>
          </div>
          <button className="small-button" data-testid="refresh-documents-button" disabled={!props.status?.course_id || props.busy !== null} onClick={() => void props.onRunTask("refresh-documents", props.onRefresh)}>
            刷新
          </button>
        </div>
        <div className="kb-document-list" data-testid="document-list">
          {visibleDocuments.map((document) => (
            <article key={document.id} className="kb-document-row" data-testid="document-row">
              <div>
                <strong>{documentDisplayName(document)}</strong>
                <span>{document.chunk_count} 条资料摘录 / {document.status}</span>
                <small>{document.parser_name ?? "默认解析器"}</small>
              </div>
              <div className="kb-document-actions">
                <button className="document-reindex-button" data-testid="reindex-document-button" disabled={props.busy !== null} onClick={() => void props.onRunTask("reindex-document", () => props.onReindex(document.id))}>
                  重建
                </button>
                <button className="document-delete-button" data-testid="delete-document-button" disabled={props.busy !== null} onClick={() => void props.onRunTask("delete-document", () => props.onDelete(document.id))}>
                  删除
                </button>
              </div>
            </article>
          ))}
          {props.knowledgeDocuments.length > 5 ? (
            <button className="kb-document-toggle" type="button" onClick={() => setShowAllDocuments((value) => !value)}>
              {showAllDocuments ? "收起资料列表" : `展开其余 ${hiddenDocumentCount} 份资料`}
            </button>
          ) : null}
          {props.knowledgeDocuments.length === 0 ? <p className="document-empty">暂无课程资料。</p> : null}
        </div>
      </aside>

      <section className="kb-main">
        <div className="kb-main-header">
          <div>
            <p className="eyebrow">资料管理员</p>
            <h2>知识库检索</h2>
          </div>
          <button className="primary-button" type="button" onClick={() => setCreateOpen(true)}>
            + 录入资料
          </button>
        </div>

        <div className="kb-search-hero">
          <input
            className="field kb-search-input"
            data-testid="knowledge-query"
            value={props.knowledgeQuery}
            onChange={(event) => props.setKnowledgeQuery(event.target.value)}
            aria-label="知识检索问题"
            placeholder="输入一个知识点、问题或学习目标，检索课程知识库"
          />
          <button
            className="primary-button"
            data-testid="search-knowledge-button"
            disabled={!props.status?.course_id || !props.knowledgeQuery.trim() || props.busy !== null}
            onClick={() => void props.onRunTask("search-knowledge", props.onSearch)}
          >
            {props.busy === "search-knowledge" ? "正在检索" : "检索知识库"}
          </button>
        </div>

        <div className="knowledge-search-results" data-testid="knowledge-search-results">
          {props.knowledgeSearchResults.map((result, index) => (
            <article key={index} className="knowledge-search-result">
              <strong>{resultDisplayName(result)}</strong>
              <span>相关度 {formatScore(result.score)} / {resultSourceLabel(result, index)}</span>
              <p className="knowledge-search-excerpt">{result.content}</p>
            </article>
          ))}
          {props.knowledgeSearchResults.length === 0 ? <EmptyState text="输入问题后检索课程知识库，结果会作为资源生成和答疑证据。" /> : null}
        </div>
      </section>

      {createOpen ? (
        <div className="modal-overlay">
          <button className="modal-backdrop" aria-label="关闭资料录入" onClick={() => setCreateOpen(false)} />
          <section className="modal-card kb-create-modal" role="dialog" aria-modal="true" aria-label="新建资料">
            <div className="modal-header">
              <div>
                <p className="eyebrow">资料接入</p>
                <h2>新建资料</h2>
              </div>
              <button className="icon-button" type="button" aria-label="关闭资料录入" onClick={() => setCreateOpen(false)}>
                ×
              </button>
            </div>
            <div className="modal-body">
              <input
                className="field"
                data-testid="knowledge-file"
                type="file"
                accept=".txt,.md,.markdown,.pdf,.docx,.pptx,.xlsx,.csv,.json,.jsonl,.ipynb,.py,.java,.js,.ts,.tsx,.jsx,.cpp,.c,.h,.hpp,.cs,.go,.rs,.sql,.html,.css,.xml,.yaml,.yml,.srt,.vtt,text/plain,text/markdown,text/csv,application/json,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.openxmlformats-officedocument.presentationml.presentation,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                onChange={(event) => {
                  const file = event.target.files?.[0] ?? null;
                  props.setKnowledgeFile(file);
                  if (file) props.setKnowledgeTitle(file.name);
                }}
                aria-label="上传资料文件"
              />
              <p className="field-help">支持 `.pptx` 幻灯片文本解析；扫描版 PDF 会在已配置本机 Tesseract OCR 时识别文字。旧版 `.ppt` 请先另存为 `.pptx`。</p>
              <div className="modal-actions">
                <button className="action-button w-full" data-testid="upload-knowledge-button" disabled={!props.status?.course_id || !props.knowledgeFile || props.busy !== null} onClick={() => void props.onRunTask("upload-knowledge", props.onUpload)}>
                  {props.busy === "upload-knowledge" ? "正在上传资料" : "上传选中文件"}
                </button>
              </div>
              {props.knowledgeImportResult ? (
                <div className="knowledge-result" data-testid="knowledge-import-result">
                  <p>{documentDisplayName(props.knowledgeImportResult.document)}</p>
                  <p>已导入 / {props.knowledgeImportResult.chunk_count} 条资料摘录 / {props.knowledgeImportResult.document.parser_name ?? "默认解析器"}</p>
                </div>
              ) : null}
              {props.knowledgeReindexResult ? (
                <div className="knowledge-result" data-testid="knowledge-reindex-result">
                  <p>重建完成：已索引 {props.knowledgeReindexResult.indexed}，跳过 {props.knowledgeReindexResult.skipped}，失败 {props.knowledgeReindexResult.failed}</p>
                  <span>{props.knowledgeReindexResult.message}</span>
                </div>
              ) : null}
              {props.knowledgeError ? <p className="error-note">{props.knowledgeError}</p> : null}
            </div>
          </section>
        </div>
      ) : null}
    </section>
  );
}
