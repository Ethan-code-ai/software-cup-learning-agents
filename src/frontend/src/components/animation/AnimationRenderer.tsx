import { useEffect, useMemo, useState } from "react";
import type { AnimationSpec } from "../../api/types";
import AnimationScene from "./AnimationScene";
import AnimationStatePanel from "./AnimationStatePanel";

export default function AnimationRenderer({ spec }: { spec: AnimationSpec }) {
  const [variantId, setVariantId] = useState(spec.data.variants[0]?.id ?? "");
  const activeVariant = useMemo(
    () => spec.data.variants.find((variant) => variant.id === variantId) ?? null,
    [spec.data.variants, variantId]
  );
  const timeline = activeVariant?.timeline ?? spec.timeline;
  const structureLabel = activeVariant?.structure_label ?? spec.data.structure_label;
  const [currentIndex, setCurrentIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const currentStep = timeline[Math.max(0, currentIndex)];
  const completedTargets = currentIndex < 0
    ? []
    : currentStep?.visited.length
      ? currentStep.visited
      : timeline.slice(0, currentIndex + 1).map((step) => step.target);

  useEffect(() => {
    setCurrentIndex(0);
    setIsPlaying(false);
  }, [variantId]);

  useEffect(() => {
    setVariantId(spec.data.variants[0]?.id ?? "");
    setCurrentIndex(0);
    setIsPlaying(false);
  }, [spec]);

  useEffect(() => {
    if (!isPlaying) return undefined;
    if (currentIndex >= timeline.length - 1) {
      setIsPlaying(false);
      return undefined;
    }
    const currentAt = timeline[Math.max(0, currentIndex)]?.at_ms ?? 0;
    const nextAt = timeline[currentIndex + 1]?.at_ms ?? currentAt + 1000;
    const timer = window.setTimeout(
      () => setCurrentIndex((index) => Math.min(index + 1, timeline.length - 1)),
      Math.max(650, nextAt - currentAt)
    );
    return () => window.clearTimeout(timer);
  }, [currentIndex, isPlaying, timeline]);

  function togglePlayback() {
    if (currentIndex >= timeline.length - 1) setCurrentIndex(0);
    setIsPlaying((playing) => !playing);
  }

  return (
    <article className="svg-animation-player" data-testid="svg-animation-player" data-template-id={spec.template_id}>
      <header className="animation-player-header">
        <div>
          <span className="animation-template-badge">SVG 实时演示</span>
          <h4>{spec.title}</h4>
          <p>{spec.description}</p>
        </div>
        <span className="animation-duration">{Math.ceil(spec.duration_ms / 1000)} 秒</span>
      </header>

      {spec.data.variants.length > 0 ? (
        <div className="animation-variant-tabs" role="tablist" aria-label="选择遍历算法">
          {spec.data.variants.map((variant) => (
            <button
              key={variant.id}
              type="button"
              role="tab"
              aria-selected={variant.id === variantId}
              className={variant.id === variantId ? "animation-variant-active" : ""}
              onClick={() => setVariantId(variant.id)}
            >
              {variant.label}
            </button>
          ))}
        </div>
      ) : null}

      <div className="animation-stage">
        <AnimationScene spec={spec} step={currentIndex < 0 ? null : currentStep} completedTargets={completedTargets} />
        <AnimationStatePanel spec={spec} step={currentIndex < 0 ? null : currentStep} structureLabel={structureLabel} />
        <div className="animation-caption" aria-live="polite">
          <span>步骤 {Math.max(0, currentIndex + 1)} / {timeline.length}</span>
          <strong data-testid="animation-step-caption">
            {currentIndex < 0 ? "点击播放，观察结构如何逐步变化" : currentStep?.caption}
          </strong>
        </div>
      </div>

      <footer className="animation-controls">
        <div className="animation-visit-order">
          <span>演示序列</span>
          <strong data-testid="animation-visit-order">
            {completedTargets.length > 0
              ? completedTargets.map((id) => spec.data.nodes.find((node) => node.id === id)?.label ?? id).join(" → ")
              : "尚未开始"}
          </strong>
        </div>
        <div className="animation-control-buttons">
          <button type="button" onClick={togglePlayback}>{isPlaying ? "暂停动画" : "播放动画"}</button>
          <button
            type="button"
            onClick={() => {
              setIsPlaying(false);
              setCurrentIndex((index) => Math.min(index + 1, timeline.length - 1));
            }}
            disabled={currentIndex >= timeline.length - 1}
          >
            下一步
          </button>
          <button type="button" onClick={() => { setIsPlaying(false); setCurrentIndex(-1); }}>重播</button>
        </div>
      </footer>
    </article>
  );
}
