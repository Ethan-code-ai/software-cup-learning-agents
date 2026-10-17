import { expect, test } from "@playwright/test";

test("教学动画根据模板数据渲染并支持逐步播放", async ({ page }) => {
  const loaded = await page.request.post("/api/v1/demo-data/load");
  expect(loaded.ok()).toBeTruthy();

  await page.goto("/");
  await page.getByRole("button", { name: "学习路径", exact: true }).click();
  const createPathButton = page.getByTestId("create-path-button");
  await createPathButton.click();
  await expect(createPathButton).toBeEnabled({ timeout: 60_000 });

  const pathTimeline = page.getByTestId("path-timeline-main");
  await pathTimeline.getByTestId("path-item-card").filter({ hasText: "二叉树遍历" }).first().click();
  await page.getByRole("button", { name: "资源生成", exact: true }).click();
  await page.getByTestId("resource-type-teaching_video").click();
  await page.getByTestId("generate-resource-button").click();

  const animation = page.getByTestId("svg-animation-player");
  await expect(animation).toBeVisible({ timeout: 60_000 });
  const svg = animation.locator("svg");
  await expect(svg).toHaveAttribute("aria-label", /二叉树/);
  const svgBox = await svg.boundingBox();
  expect(svgBox?.width).toBeGreaterThan(240);
  await expect(animation.getByTestId("animation-step-caption")).toContainText("根节点 A");

  await animation.getByRole("button", { name: "下一步" }).click();
  await expect(animation.getByTestId("animation-visit-order")).toContainText("A → B");

  await animation.getByRole("button", { name: "重播" }).click();
  await expect(animation.getByTestId("animation-visit-order")).toContainText("尚未开始");

  await page.getByRole("button", { name: "学习路径", exact: true }).click();
  await pathTimeline.getByTestId("path-item-card").filter({ hasText: "BFS/DFS" }).first().click();
  await page.getByRole("button", { name: "资源生成", exact: true }).click();
  await page.getByTestId("resource-type-teaching_video").click();
  await page.getByTestId("generate-resource-button").click();

  const graphAnimation = page.getByTestId("svg-animation-player");
  await expect(graphAnimation).toHaveAttribute("data-template-id", "graph_visualizer", { timeout: 60_000 });
  await expect(graphAnimation.getByTestId("animation-scene").locator("circle")).toHaveCount(5);
  await expect(graphAnimation.getByRole("tab", { name: "BFS 广度优先" })).toHaveAttribute("aria-selected", "true");
  await expect(graphAnimation.getByTestId("animation-state-panel")).toContainText("Queue 队列");
  await graphAnimation.getByRole("button", { name: "下一步" }).click();
  await expect(graphAnimation.getByTestId("animation-visit-order")).toContainText("A → B");
  await expect(graphAnimation.getByTestId("animation-frontier")).toContainText("Front");

  await graphAnimation.getByRole("tab", { name: "DFS 深度优先" }).click();
  await expect(graphAnimation.getByTestId("animation-state-panel")).toContainText("Stack 栈");
  await graphAnimation.getByRole("button", { name: "下一步" }).click();
  await graphAnimation.getByRole("button", { name: "下一步" }).click();
  await expect(graphAnimation.getByTestId("animation-visit-order")).toContainText("A → B → D");
  await expect(graphAnimation.getByTestId("animation-frontier")).toContainText("Top");
});

test("栈和队列动画展示真实入栈出栈与入队出队", async ({ page }) => {
  const loaded = await page.request.post("/api/v1/demo-data/load");
  expect(loaded.ok()).toBeTruthy();

  await page.goto("/");
  await page.getByRole("button", { name: "学习路径", exact: true }).click();
  await page.getByLabel("学习目标").fill("为数据结构小测做准备，先补栈和队列的 push pop enqueue dequeue 基本操作");
  const createPathButton = page.getByTestId("create-path-button");
  await createPathButton.click();
  await expect(createPathButton).toBeEnabled({ timeout: 60_000 });

  const pathTimeline = page.getByTestId("path-timeline-main");
  await pathTimeline.getByTestId("path-item-card").filter({ hasText: "栈" }).first().click();
  await page.getByRole("button", { name: "资源生成", exact: true }).click();
  await page.getByTestId("resource-type-teaching_video").click();
  await page.getByTestId("generate-resource-button").click();

  let animation = page.getByTestId("svg-animation-player");
  await expect(animation).toHaveAttribute("data-template-id", "stack_queue_operations", { timeout: 60_000 });
  await expect(animation.getByTestId("animation-frontier")).toContainText("13 · Top");
  await animation.getByRole("button", { name: "下一步" }).click();
  await expect(animation.getByTestId("animation-frontier")).toContainText("21 · Top");
  await animation.getByRole("button", { name: "下一步" }).click();
  await expect(animation.getByTestId("animation-frontier")).toContainText("34 · Top");
  await animation.getByRole("button", { name: "下一步" }).click();
  await expect(animation.getByTestId("animation-frontier")).toContainText("21 · Top");
  await expect(animation.getByTestId("animation-step-caption")).toContainText("pop()");
  await expect(animation.getByTestId("animation-operation")).toContainText("pop · 弹栈");

  await page.getByRole("button", { name: "学习路径", exact: true }).click();
  await pathTimeline.getByTestId("path-item-card").filter({ hasText: "队列" }).first().click();
  await page.getByRole("button", { name: "资源生成", exact: true }).click();
  await page.getByTestId("resource-type-teaching_video").click();
  await page.getByTestId("generate-resource-button").click();

  animation = page.getByTestId("svg-animation-player");
  await expect(animation.getByTestId("animation-frontier")).toContainText("Front · 8");
  await animation.getByRole("button", { name: "下一步" }).click();
  await animation.getByRole("button", { name: "下一步" }).click();
  await expect(animation.getByTestId("animation-frontier")).toContainText("34 · Rear");
  await animation.getByRole("button", { name: "下一步" }).click();
  await expect(animation.getByTestId("animation-frontier")).toContainText("Front · 13");
  await expect(animation.getByTestId("animation-step-caption")).toContainText("dequeue()");
  await expect(animation.getByTestId("animation-operation")).toContainText("dequeue · 出队");
});
