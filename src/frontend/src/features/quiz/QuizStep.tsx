import type { AgentRun, Quiz } from "../../api/types";
import { InlineAgentTrace } from "../../components/AgentTrace";
import { AgentLoading, EmptyState, MarkdownBlock, Panel, SafetyStatusBanner } from "../../components/common";
import { SourceEvidence } from "../../components/ResourceOutput";

function quizQuestionTypeLabel(questionType?: string | null) {
  const labels: Record<string, string> = {
    multiple_choice: "选择题",
    fill_blank: "填空题",
    short_answer: "简答题",
    application: "应用题",
    code_analysis: "代码分析题"
  };
  return labels[questionType ?? ""] ?? "练习题";
}

export default function QuizStep({
  busy,
  quiz,
  canGenerateQuiz,
  attemptText,
  onAttemptTextChange,
  autoProfileUpdateEnabled,
  onAutoProfileUpdateEnabledChange,
  runs,
  traceVisible,
  onGenerateQuiz,
  onSubmitAttempt
}: {
  busy: string | null;
  quiz: Quiz | null;
  canGenerateQuiz: boolean;
  attemptText: string;
  onAttemptTextChange: (value: string) => void;
  autoProfileUpdateEnabled: boolean;
  onAutoProfileUpdateEnabledChange: (value: boolean) => void;
  runs: AgentRun[];
  traceVisible: boolean;
  onGenerateQuiz: () => void;
  onSubmitAttempt: () => void;
}) {
  return (
    <Panel title="练习测验" kicker="出题与评估">
      <button
        className="primary-button"
        data-testid="generate-quiz-button"
        disabled={!canGenerateQuiz || busy !== null}
        onClick={onGenerateQuiz}
      >
        {busy === "generate-quiz" ? "正在生成测验" : "生成当前节点测验"}
      </button>
      {busy === "generate-quiz" ? <AgentLoading testId="quiz-loading" title="出题老师正在生成测验" detail="题目会结合当前概念和学生画像。" /> : null}
      <InlineAgentTrace action="quiz" busy={busy === "generate-quiz"} runs={runs} visible={traceVisible} />
      {quiz ? (
        <div className="quiz-box">
          <SafetyStatusBanner status={quiz.safety_status} message={quiz.safety_message} />
          {quiz.fallback_used ? <p className="muted-text">大模型出题暂不可用，已安全降级：{quiz.fallback_reason ?? "rule-based fallback"}</p> : null}
          {quiz.items.map((item, index) => (
            <article key={index} className="quiz-question" data-testid="quiz-question">
              <strong>第 {index + 1} 题 · {quizQuestionTypeLabel(item.question_type)}</strong>
              <MarkdownBlock text={item.question} />
              {item.options?.length ? (
                <ul>
                  {item.options.map((option) => <li key={option}>{option}</li>)}
                </ul>
              ) : null}
              <SourceEvidence sourceRefs={item.source_refs ?? []} />
            </article>
          ))}
          {quiz.items.length > 0 ? (
            <>
              <textarea
                className="field min-h-28 resize-none"
                data-testid="quiz-answer"
                value={attemptText}
                onChange={(event) => onAttemptTextChange(event.target.value)}
                aria-label="作答内容"
                placeholder="在这里输入你的作答思路"
              />
              <label className="setting-toggle">
                <input
                  data-testid="auto-profile-update-toggle"
                  type="checkbox"
                  checked={autoProfileUpdateEnabled}
                  disabled={busy !== null}
                  onChange={(event) => onAutoProfileUpdateEnabledChange(event.target.checked)}
                />
                <span>
                  <strong>评估后后台更新画像与路径</strong>
                  <small>成绩会先返回，画像顾问和学习规划师随后在后台更新当前学习路径。</small>
                </span>
              </label>
              <button className="primary-button" data-testid="submit-answer-button" disabled={!attemptText.trim() || busy !== null} onClick={onSubmitAttempt}>
                {busy === "submit-attempt" ? "正在提交作答" : busy === "sync-profile" ? "正在更新画像" : "提交作答并评估"}
              </button>
              {busy === "submit-attempt" ? <AgentLoading testId="evaluator-loading" title="测评教师正在评分" detail="系统正在比较评分规则和作答内容。" /> : null}
              {busy === "sync-profile" ? <AgentLoading testId="profile-update-loading" title="画像顾问正在更新画像" detail="系统正在分析最新学习轨迹。" /> : null}
            </>
          ) : null}
        </div>
      ) : (
        <EmptyState text="生成测验后，这里会展示当前节点的练习题。" />
      )}
    </Panel>
  );
}
