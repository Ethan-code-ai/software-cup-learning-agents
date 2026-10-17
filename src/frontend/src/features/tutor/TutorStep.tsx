import type { RefObject } from "react";

import type { AgentRun } from "../../api/types";
import { InlineAgentTrace } from "../../components/AgentTrace";
import { SafetyStatusBanner, StatusTracker, TypewriterMarkdown } from "../../components/common";
import { SourceEvidence } from "../../components/ResourceOutput";

type TutorMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  sourceRefs?: Array<Record<string, unknown>>;
  safetyStatus?: "passed" | "blocked" | "degraded";
  safetyMessage?: string | null;
};

export default function TutorStep({
  busy,
  canUseLoop,
  question,
  onQuestionChange,
  messages,
  chatScrollRef,
  runs,
  traceVisible,
  learningTraceUpdateNotice,
  onAskTutor
}: {
  busy: string | null;
  canUseLoop: boolean;
  question: string;
  onQuestionChange: (value: string) => void;
  messages: TutorMessage[];
  chatScrollRef: RefObject<HTMLDivElement | null>;
  runs: AgentRun[];
  traceVisible: boolean;
  learningTraceUpdateNotice: string | null;
  onAskTutor: () => void;
}) {
  return (
    <section className="tutor-workspace" aria-label="教师答疑">
      <div className="chat-shell">
        <div className="chat-heading">
          <div>
            <p className="eyebrow">答疑教师</p>
            <h2>教师答疑</h2>
          </div>
        </div>
        <div className="chat-messages" ref={chatScrollRef}>
          <article className="chat-message chat-message-assistant">
            <span>答疑教师</span>
            <p>我会结合你的学生画像和课程知识库，用可追溯证据解释问题。可以直接输入你的困惑。</p>
          </article>
          {messages.map((message) => (
            <article
              className={`chat-message ${message.role === "user" ? "chat-message-user" : "chat-message-assistant chat-message-rich"}`}
              key={message.id}
            >
              <span>{message.role === "user" ? "学生提问" : "辅导答复"}</span>
              {message.role === "assistant" ? <TypewriterMarkdown text={message.content} /> : <p>{message.content}</p>}
              {message.role === "assistant" ? (
                <SafetyStatusBanner status={message.safetyStatus} message={message.safetyMessage} />
              ) : null}
              {message.role === "assistant" ? <SourceEvidence sourceRefs={message.sourceRefs ?? []} /> : null}
            </article>
          ))}
          {busy === "ask-tutor" ? (
            <article className="chat-message chat-message-assistant">
              <span>答疑教师</span>
              <StatusTracker
                compact
                testId="tutor-loading"
                steps={[
                  { label: "检索证据", detail: "已锁定课程资料与相关知识点", status: "done" },
                  { label: "组织解释", detail: "答疑教师正在按你的画像调整讲解方式", status: "active" },
                  { label: "安全校验", detail: "安全校验通过后展示完整回答", status: "pending" }
                ]}
              />
            </article>
          ) : null}
        </div>
        <div className="chat-composer">
          <textarea
            className="field chat-input resize-none"
            data-testid="tutor-question"
            value={question}
            onChange={(event) => onQuestionChange(event.target.value)}
            aria-label="辅导问题"
            placeholder="输入你想追问的知识点、代码问题或解题思路..."
          />
          <button
            className="chat-send-button"
            data-testid="ask-tutor-button"
            disabled={!canUseLoop || !question.trim() || busy !== null}
            onClick={onAskTutor}
          >
            {busy === "ask-tutor" ? "生成中" : "发送"}
          </button>
        </div>
        <InlineAgentTrace action="tutor" busy={busy === "ask-tutor"} runs={runs} visible={traceVisible} />
        {learningTraceUpdateNotice ? <p className="ai-disclaimer">{learningTraceUpdateNotice}</p> : null}
        <p className="ai-disclaimer">* 教师团队生成内容仅供参考，请注意甄别事实（已开启内容安全与防幻觉过滤机制）*</p>
      </div>
    </section>
  );
}
