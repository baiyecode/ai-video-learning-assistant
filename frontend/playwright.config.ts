import { defineConfig, devices } from "@playwright/test";

/**
 * Golden paths only (see e2e/golden-path*.spec.ts). Both servers start
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
              // The dev server proxies ``/api`` with ``changeOrigin``, so the backend sees
              // its own ``:8000`` origin while the browser sends ``Origin: :5173``. Without
              // this allowance the cookie refresh (``POST /auth/refresh``) would be refused
              // and every page reload would drop the Session.
              APP_CORS_ORIGINS: '["http://127.0.0.1:5173"]',
              // The fake mailer's verification link must open in this very browser
              // session, so the backend builds it against the dev-server origin.
              APP_FRONTEND_BASE_URL: "http://127.0.0.1:5173",
              // P2-09's second golden path covers 抖音 parsing + Download, so the
              // feature switch ships open in fake-adapter mode. The 429 leg counts on
              // the default free allowance; Stripe keys stay empty (demo gateway).
              APP_DOUYIN_ENABLED: "1",
              APP_ANALYSIS_DAILY_QUOTA: "3",
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
