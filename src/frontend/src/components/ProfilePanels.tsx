import type { StudentProfile, StudentProfileHistory } from "../api/types";

const profileDimensions = [
  ["learning_goal", "学习目标"],
  ["foundation_level", "知识基础"],
  ["learning_preference", "认知风格"],
  ["available_time", "可用时间"],
  ["weak_points", "易错短板"],
  ["resource_preference", "资源偏好"]
] as const;

const dimensionLabels = Object.fromEntries(profileDimensions);

export function ProfileHistoryPanel({ history }: { history: StudentProfileHistory[] }) {
  const latest = history[0];
  return (
    <section className="profile-history" data-testid="profile-history">
      <div className="profile-history-heading">
        <div>
          <span className="eyebrow">画像更新</span>
          <h3>画像变化历史</h3>
        </div>
        <small>{history.length ? `${history.length} 次更新` : "暂无记录"}</small>
      </div>

      {!latest ? (
        <p className="muted">暂无画像变化记录。</p>
      ) : (
        <>
          <article className="profile-history-latest" data-testid="profile-latest-change">
            <div>
              <span>最近一次</span>
              <strong>{triggerTypeLabel(latest.trigger_type)}</strong>
            </div>
            <p>{shortText(latest.reason, 86)}</p>
            <div className="profile-history-tags">
              {changedDimensionLabels(latest).map((label) => (
                <span key={label}>{label}</span>
              ))}
            </div>
          </article>

          <div className="profile-history-list">
            {history.map((record) => (
              <article key={record.id} className="profile-history-record">
                <div className="profile-history-record-head">
                  <div>
                    <strong>{triggerTypeLabel(record.trigger_type)}</strong>
                    <small>{record.created_at ? new Date(record.created_at).toLocaleString() : ""}</small>
                  </div>
                  <span>{record.changed_dimensions.length || 0} 项变化</span>
                </div>
                <div className="profile-history-tags">
                  {changedDimensionLabels(record).map((label) => (
                    <span key={label}>{label}</span>
                  ))}
                </div>
                <p>{shortText(record.reason, 96)}</p>
                <details className="profile-history-detail">
                  <summary>查看具体变化</summary>
                  <div>{userFacingChangeSummary(record)}</div>
                  <small>{profileEvidenceSummary(record)}</small>
                </details>
              </article>
            ))}
          </div>
        </>
      )}
    </section>
  );
}

export function ProfileDimensionList({ profile }: { profile: StudentProfile }) {
  const dimensionIcons: Record<string, string> = {
    learning_goal: "🎯",
    foundation_level: "📊",
    learning_preference: "🧠",
    available_time: "⏱️",
    weak_points: "🩹",
    resource_preference: "📚"
  };

  return (
    <div className="modern-profile-card" data-testid="profile-dimensions">
      <div className="modern-profile-header">
        <span className="pulse-dot" aria-hidden="true" />
        <h3>六维动态学生画像</h3>
      </div>
      <div className="modern-dimension-grid">
        {profileDimensions.map(([key, label]) => {
          const value = formatPreference(profile, key);
          return (
            <article key={key} className="modern-dimension-item">
              <span className="dimension-label">
                <span aria-hidden="true">{dimensionIcons[key] ?? "•"}</span>
                {label}
              </span>
              {key === "foundation_level" ? (
                <p className="dimension-value">
                  <span className="status-badge">{value}</span>
                </p>
              ) : (
                <p className="dimension-value">{value}</p>
              )}
            </article>
          );
        })}
      </div>
      {profile.preferences.last_profile_update_reason ? (
        <footer className="modern-profile-footer" data-testid="profile-update-reason">
          <span aria-hidden="true">✨</span>
          <p>{userFacingText(String(profile.preferences.last_profile_update_reason))}</p>
        </footer>
      ) : null}
    </div>
  );
}

export function ProfileSkeleton() {
  return (
    <div className="modern-profile-card profile-skeleton-card" data-testid="profile-skeleton" aria-live="polite">
      <div className="modern-profile-header">
        <span className="pulse-dot" aria-hidden="true" />
        <h3>画像顾问正在扫描六维特征</h3>
      </div>
      <div className="modern-dimension-grid">
        {profileDimensions.map(([key, label]) => (
          <article key={key} className="modern-dimension-item skeleton-dimension">
            <span className="dimension-label">{label}</span>
            <i />
            <b />
          </article>
        ))}
      </div>
      <footer className="modern-profile-footer">
        <span aria-hidden="true">✨</span>
        <p>正在从对话中抽取学习目标、基础水平、偏好与短板。</p>
      </footer>
    </div>
  );
}

function formatPreference(profile: StudentProfile, key: string): string {
  const value = profile.preferences[key];
  if (value === undefined || value === null || value === "") {
    if (key === "learning_goal") return userFacingText(profile.goal);
    if (key === "foundation_level") return displayProfileValue(key, profile.level);
    if (key === "available_time") return userFacingText(profile.time_budget);
    return "等待学习过程更新";
  }
  return displayProfileValue(key, String(value));
}

function triggerTypeLabel(value: string): string {
  const labels: Record<string, string> = {
    dialogue: "根据对话更新",
    profile_build: "画像首次建立",
    resource: "根据资源学习更新",
    tutor: "根据答疑互动更新",
    quiz: "根据测验表现更新",
    assessment: "根据学习评估更新",
    manual: "手动更新"
  };
  return labels[value] ?? "学习过程更新";
}

function changedDimensionLabels(record: StudentProfileHistory): string[] {
  if (record.changed_dimensions.length === 0) return ["无明显变化"];
  return record.changed_dimensions.map((key) => dimensionLabels[key] ?? key);
}

function shortText(value: string, maxLength: number): string {
  const normalized = userFacingText(value).replace(/\s+/g, " ").trim();
  return normalized.length > maxLength ? `${normalized.slice(0, maxLength - 1)}...` : normalized;
}

function userFacingChangeSummary(record: StudentProfileHistory): string {
  if (record.changed_dimensions.length === 0) return "本次画像保持稳定，暂未发现明显变化。";
  return record.changed_dimensions
    .map((key) => {
      const label = dimensionLabels[key] ?? key;
      const before = displayProfileValue(key, record.before_dimensions[key] ?? "未记录");
      const after = displayProfileValue(key, record.after_dimensions[key] ?? "未记录");
      return `${label}：${before} → ${after}`;
    })
    .join("；");
}

function displayProfileValue(key: string, value: string): string {
  const text = userFacingText(String(value));
  const labels: Record<string, string> = {
    step_by_step: "分步骤讲解",
    worked_examples: "案例演示",
    code_driven: "代码实践",
    visual_map: "图解梳理",
    guided_note: "讲解文档",
    practice_questions: "练习题库",
    mind_map: "思维导图",
    extended_reading: "拓展阅读",
    coding_case: "代码实操",
    beginner: "基础入门",
    intermediate: "进阶理解",
    advanced: "高阶提升",
    none: "暂无记录",
    unknown: "暂无记录"
  };
  return labels[text] ?? text;
}

function userFacingText(value: string): string {
  return String(value)
    .replace(/L(?:LM)\s*ProfileUpdater/gi, "系统")
    .replace(/ProfileUpdater\s*A(?:gent)/gi, "画像顾问")
    .replace(/A(?:gent)\s*step/gi, "学习记录")
    .replace(/A(?:gent)\s*trace/gi, "学习记录")
    .replace(/execution_mode\s*=\s*[^；;。,\s]+[；;。]?/gi, "")
    .replace(/\bLLM\b/gi, "智能分析")
    .replace(/\bAgent\b/gi, "智能体")
    .replace(/rule[-_ ]based/gi, "本地规则")
    .replace(/step_by_step/g, "分步骤讲解")
    .replace(/worked_examples/g, "案例演示")
    .replace(/code_driven/g, "代码实践")
    .replace(/visual_map/g, "图解梳理")
    .replace(/guided_note/g, "讲解文档")
    .replace(/practice_questions/g, "练习题库")
    .replace(/mind_map/g, "思维导图")
    .replace(/extended_reading/g, "拓展阅读")
    .replace(/coding_case/g, "代码实操")
    .replace(/beginner/g, "基础入门")
    .replace(/intermediate/g, "进阶理解")
    .replace(/advanced/g, "高阶提升")
    .replace(/\?{2,}/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function profileEvidenceSummary(record: StudentProfileHistory): string {
  if (record.evidence_refs.length === 0) return "依据：来自本次对话或学习行为。";
  return `依据：系统参考了 ${record.evidence_refs.length} 条对话或学习行为线索。`;
}
