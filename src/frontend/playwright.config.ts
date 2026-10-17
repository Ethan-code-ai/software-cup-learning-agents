import { defineConfig } from "@playwright/test";

const browserChannel = process.env.PLAYWRIGHT_CHANNEL ?? (process.platform === "win32" ? "msedge" : undefined);

export default defineConfig({
  testDir: "./tests",
  timeout: 60_000,
  expect: {
    timeout: 10_000
  },
  reporter: [["list"]],
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:5174",
    browserName: "chromium",
    channel: browserChannel,
    headless: true,
    trace: "retain-on-failure"
  }
});
