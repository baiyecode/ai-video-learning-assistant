import { defineConfig, devices } from "@playwright/test";

/**
 * One golden path only (see e2e/golden-path.spec.ts). It is skipped unless
 * PLAYWRIGHT_E2E=1, because it needs a running frontend + backend with fake adapters.
 *
 *   PLAYWRIGHT_E2E=1 npx playwright test
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  timeout: 60_000,
  reporter: process.env.CI ? [["github"], ["list"]] : [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:5173",
    trace: "on-first-retry",
    locale: "zh-CN",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
