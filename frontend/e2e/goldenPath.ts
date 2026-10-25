/**
 * Shared steps for the browser golden paths (ticket P2-09).
 *
 * Both specs drive the same SPA against the fake-adapter servers Playwright starts
 * (see ``playwright.config.ts``). Everything a real user clicks stays in the browser;
 * the two things a test cannot click its way through - reading the fake mailbox and
 * paying on a hosted checkout page - go through the very same HTTP endpoints the
 * product exposes: ``GET /api/demo/inbox``, ``POST /api/billing/checkout`` and the
 * signed ``POST /api/billing/webhook``.
 */

import { expect, type APIRequestContext, type Page } from "@playwright/test";
import { createHmac } from "node:crypto";

/** Mirrors ``DEMO_WEBHOOK_SECRET`` in ``backend/app/adapters/demo.py``. */
const DEMO_WEBHOOK_SECRET = "whsec_demo";

export const PASSWORD = "e2e-password-123";

export const DEMO_YOUTUBE_URL = "https://www.youtube.com/watch?v=demoP1Video";
export const DEMO_YOUTUBE_TITLE = "演示视频：从零理解间隔重复";

/** Quota-burning / post-upgrade Analyses each need their own Video, so each gets its own id. */
export function demoYouTubeUrl(platformVideoId: string): string {
  return `https://www.youtube.com/watch?v=${platformVideoId}`;
}

export function randomEmail(): string {
  return `e2e-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@example.com`;
}

/**
 * Register, then sign in - the two steps P2-06 split apart.
 *
 * The page must already be on ``/login`` (``?next=`` included). Registration answers
 * one neutral sentence and hands the form back on the 登录 tab with the credentials
 * still filled in; the caller asserts wherever the sign-in redirect landed.
 */
export async function signUpAndSignIn(page: Page, email: string): Promise<void> {
  // The tab and the submit button share the 注册 label since P2-06, so the tab is
  // addressed positionally (tabs render before the form) and the submit by type.
  await page.getByRole("button", { name: "注册", exact: true }).first().click();
  await page.getByLabel("邮箱").fill(email);
  await page.getByLabel("密码").fill(PASSWORD);
  await page.locator('form button[type="submit"]').click();

  await expect(page.getByRole("status")).toContainText("请查收邮箱中的验证邮件");

  await page.getByLabel("邮箱").fill(email);
  await page.getByLabel("密码").fill(PASSWORD);
  await page.locator('form button[type="submit"]').click();
  await expect(page.getByRole("button", { name: "退出登录" })).toBeVisible();
}

/** Resolve a page address on the home screen and wait for its result card. */
export async function resolveOnHome(page: Page, url: string, title: string): Promise<void> {
  await page.getByLabel("页面地址").fill(url);
  await page.getByRole("button", { name: "解析视频" }).click();
  await expect(page.getByRole("heading", { level: 2, name: title })).toBeVisible();
}

/** Back to the home screen without a reload: the in-memory access token survives. */
export async function backToHome(page: Page): Promise<void> {
  // ``exact`` because the Analysis screen also carries a "← 返回首页" link.
  await page.getByRole("link", { name: "首页", exact: true }).click();
}

/**
 * Confirm the one-time email link the fake mailer delivered.
 *
 * The demo inbox route hands back the raw token, which is what the ``/verify-email``
 * page posts. Two legs of the funnel then stay deterministic: this HTTP confirmation
 * for the Quota chain, and the real page click-through in
 * ``golden-path-subscription.spec.ts``.
 */
export async function verifyEmailFromDemoInbox(request: APIRequestContext, email: string): Promise<void> {
  const token = await demoVerificationToken(request, email);
  const confirmed = await request.post("/api/auth/verification/confirm", { data: { token } });
  expect(confirmed.status(), await confirmed.text()).toBe(200);
}

/** The one-time token the fake mailer put in the verification link. */
export async function demoVerificationToken(request: APIRequestContext, email: string): Promise<string> {
  const inbox = await request.get(`/api/demo/inbox?to=${encodeURIComponent(email)}`);
  expect(inbox.status(), await inbox.text()).toBe(200);
  const messages = (await inbox.json()) as { verification_token: string | null }[];
  expect(messages.length, `no verification mail for ${email}`).toBeGreaterThan(0);

  const token = messages[0].verification_token;
  expect(token, "the demo inbox must carry the verification token").toBeTruthy();
  return token as string;
}

/**
 * The upgrade: ask for the fake hosted checkout, then inject the payment-success webhook.
 *
 * Signed with the demo webhook secret and a run-unique event id, so re-running the
 * golden path against the persisted e2e database never lands on the idempotency gate.
 */
export async function payForSubscription(request: APIRequestContext, email: string): Promise<void> {
  const session = await request.post("/api/auth/login", { data: { email, password: PASSWORD } });
  expect(session.status(), await session.text()).toBe(200);
  const { access_token: accessToken, account } = (await session.json()) as {
    access_token: string;
    account: { id: string };
  };

  const checkout = await request.post("/api/billing/checkout", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  expect(checkout.status(), await checkout.text()).toBe(200);
  const { url } = (await checkout.json()) as { url: string };
  expect(url).toContain("https://checkout.demo.invalid/");

  await injectPaymentSuccess(request, account.id);
}

export async function injectPaymentSuccess(request: APIRequestContext, accountId: string): Promise<void> {
  const created = Math.floor(Date.now() / 1000);
  const payload = JSON.stringify({
    id: `evt_e2e_${created}_${Math.random().toString(36).slice(2, 8)}`,
    type: "checkout.session.completed",
    created,
    data: {
      object: {
        client_reference_id: accountId,
        customer: "cus_e2e",
        subscription: `sub_e2e_${created}`,
        current_period_end: created + 30 * 24 * 60 * 60,
        metadata: { price_id: "price_e2e_monthly" },
      },
    },
  });
  // Stripe's scheme: HMAC-SHA256 over "<t>.<raw body>" keyed by the webhook secret.
  const signature = createHmac("sha256", DEMO_WEBHOOK_SECRET).update(`${created}.${payload}`).digest("hex");

  const webhook = await request.post("/api/billing/webhook", {
    data: payload,
    headers: { "Content-Type": "application/json", "Stripe-Signature": `t=${created},v1=${signature}` },
  });
  expect(webhook.status(), await webhook.text()).toBe(200);
  expect(await webhook.json()).toEqual({ received: true });
}

/** Membership as the backend reports it - the truth every P2-08 screen renders from. */
export async function readMembership(request: APIRequestContext, email: string): Promise<{ status: string; vip_active: boolean }> {
  const session = await request.post("/api/auth/login", { data: { email, password: PASSWORD } });
  const { access_token: accessToken } = (await session.json()) as { access_token: string };
  const membership = await request.get("/api/me/membership", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  expect(membership.status(), await membership.text()).toBe(200);
  return (await membership.json()) as { status: string; vip_active: boolean };
}
