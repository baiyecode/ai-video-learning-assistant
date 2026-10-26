import { defineConfig, devices } from "@playwright/test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import {
  DEFAULT_DAILY_FREE_ANALYSIS_LIMIT,
  DEFAULT_MONTHLY_PRICE_USD,
} from "./src/lib/billing-defaults";

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

/** Prefix for the per-run temp directory; ``e2e/global-teardown.ts`` relies on it. */
const RUN_ROOT_PREFIX = "ai-video-e2e-";

type RunScope = {
  databaseUrl: string;
  dataDir: string;
};

/** Absolute SQLite URL with forward slashes, e.g. `sqlite+aiosqlite:///C:/tmp/x/e2e.db`. */
function sqliteUrl(filePath: string): string {
  return `sqlite+aiosqlite:///${filePath.replace(/\\/g, "/")}`;
}

/**
 * Run-scoped, empty database and data directory.
 *
 * Every `PLAYWRIGHT_E2E=1` run gets its own directory under the OS temp directory
 * (`fs.mkdtempSync` never reuses a name). The database is constructed as empty by
 * the run itself: nothing is copied, and nothing has to be deleted beforehand -
 * the first backend connection creates `e2e.db` and the app's startup hook creates
 * the schema. A crashed or failed previous run therefore cannot leak state into
 * this one. `e2e/global-teardown.ts` removes only the directory created here.
 *
 * `E2E_RUN_ROOT` is the hand-off to Playwright worker processes, which inherit the
 * main process environment and re-evaluate this config: only the evaluation that
 * creates the directory logs it; workers reuse the existing path. If the variable is
 * already set (e.g. by a debugging shell), that directory is used as-is.
 */
function createRunScope(): RunScope {
  const existingRoot = process.env.E2E_RUN_ROOT;
  const root = existingRoot ?? fs.mkdtempSync(path.join(os.tmpdir(), RUN_ROOT_PREFIX));
  process.env.E2E_RUN_ROOT = root;

  const dataDir = path.join(root, "data");
  fs.mkdirSync(dataDir, { recursive: true });
  const databaseUrl = sqliteUrl(path.join(root, "e2e.db"));

  if (!existingRoot) {
    console.log(`[e2e] fresh run-scoped database: ${databaseUrl}`);
  }
  return { databaseUrl, dataDir };
}

const runScope = enabled ? createRunScope() : undefined;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  // Spec files run in parallel (Playwright's default worker count) against one
  // fake-adapter backend and one run-scoped SQLite file. That is deliberate: resolving
  // a Video is idempotent (#54), and every test creates run-unique data (Accounts,
  // platform video ids). e2e/concurrent-resolve.spec.ts pins the empty-database race
  // that used to force a single worker. `fullyParallel: false` still keeps the tests
  // inside one file in declaration order.
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
  // Deletes only the run-scoped temp directory; see the comment on `createRunScope`.
  globalTeardown: "./e2e/global-teardown.ts",
  ...(runScope
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
              APP_DATABASE_URL: runScope.databaseUrl,
              APP_DATA_DIR: runScope.dataDir,
              APP_AUTH_COOKIE_SECURE: "false",
              // No APP_CORS_ORIGINS: the dev server proxies ``/api`` and keeps the
              // browser's Host, so the backend's own origin matches the one the browser
              // sends and the same-origin path (no CORS allowance) is what is tested.
              // The fake mailer's verification link must open in this very browser
              // session, so the backend builds it against the dev-server origin.
              APP_FRONTEND_BASE_URL: "http://127.0.0.1:5173",
              // P2-09's second golden path covers 抖音 parsing + Download, so the
              // feature switch ships open in fake-adapter mode. The 429 leg counts on
              // the default free allowance; Stripe keys stay empty (demo gateway).
              APP_DOUYIN_ENABLED: "1",
              // Pin both sides of the price mirror to the same committed defaults, so a
              // repriced shell cannot make /me/membership and the Articles disagree.
              APP_SUBSCRIPTION_MONTHLY_USD: String(DEFAULT_MONTHLY_PRICE_USD),
              APP_ANALYSIS_DAILY_QUOTA: String(DEFAULT_DAILY_FREE_ANALYSIS_LIMIT),
              // Rate limits and the visitor hourly cap would make repeat runs flaky;
              // the backend suite covers them at the HTTP seam.
              APP_RATE_LIMIT_RESOLVE_PER_MINUTE: "0",
              APP_RATE_LIMIT_DOWNLOAD_PER_MINUTE: "0",
              APP_RATE_LIMIT_LOGIN_PER_15_MINUTES: "0",
              APP_RATE_LIMIT_REGISTER_PER_HOUR: "0",
              APP_RATE_LIMIT_VERIFICATION_CONFIRM_PER_HOUR: "0",
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
            env: {
              ...inheritedEnv,
              VITE_SENTRY_DSN: "",
              // Pin the display mirrors so the golden-path assertions on the seeded
              // copy stay deterministic even when the caller's shell exports a
              // repriced build.
              VITE_SUBSCRIPTION_MONTHLY_USD: String(DEFAULT_MONTHLY_PRICE_USD),
              VITE_ANALYSIS_DAILY_QUOTA: String(DEFAULT_DAILY_FREE_ANALYSIS_LIMIT),
            },
          },
        ],
      }
    : {}),
});
