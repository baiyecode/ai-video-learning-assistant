import { defineConfig, devices } from "@playwright/test";

/**
 * One golden path only (see e2e/golden-path.spec.ts). Both servers start
 * automatically with deterministic adapters when PLAYWRIGHT_E2E=1.
 *
 *   PLAYWRIGHT_E2E=1 npx playwright test
 */
const enabled = process.env.PLAYWRIGHT_E2E === "1";

const inheritedEnv = Object.fromEntries(
  Object.entries(process.env).filter((entry): entry is [string, string] => entry[1] !== undefined),
);

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  timeout: 60_000,
  reporter: process.env.CI ? [["github"], ["list"]] : [["list"]],
  use: {
    baseURL: "http://127.0.0.1:5173",
    trace: "on-first-retry",
    locale: "zh-CN",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  ...(enabled
    ? {
        webServer: [
          {
            command: "uv run uvicorn app.main:app --host 127.0.0.1 --port 8000",
            cwd: "../backend",
            url: "http://127.0.0.1:8000/health",
            timeout: 120_000,
            reuseExistingServer: false,
            env: {
              ...inheritedEnv,
              APP_FAKE_ADAPTERS: "1",
              APP_ENV: "development",
              APP_SECRET_KEY: "e2e-secret-key-not-for-production",
              APP_DATABASE_URL: "sqlite+aiosqlite:///./data/e2e.db",
              APP_DATA_DIR: "./data/e2e",
              APP_AUTH_COOKIE_SECURE: "false",
              // Rate limits and the visitor hourly cap would make repeat runs flaky;
              // the backend suite covers them at the HTTP seam.
              APP_RATE_LIMIT_RESOLVE_PER_MINUTE: "0",
              APP_RATE_LIMIT_DOWNLOAD_PER_MINUTE: "0",
              APP_RATE_LIMIT_LOGIN_PER_15_MINUTES: "0",
              APP_RATE_LIMIT_REGISTER_PER_HOUR: "0",
              APP_RATE_LIMIT_ANALYSIS_SECONDS: "0",
              APP_RATE_LIMIT_REPORT_PER_HOUR: "0",
              APP_DOWNLOAD_VISITOR_HOURLY_LIMIT: "100",
              SENTRY_DSN: "",
            },
          },
          {
            command: "npm run dev -- --host 127.0.0.1 --port 5173",
            url: "http://127.0.0.1:5173",
            timeout: 120_000,
            reuseExistingServer: false,
            env: { ...inheritedEnv, VITE_SENTRY_DSN: "" },
          },
        ],
      }
    : {}),
});
