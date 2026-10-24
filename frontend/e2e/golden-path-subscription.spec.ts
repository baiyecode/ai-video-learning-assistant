import { expect, test } from "@playwright/test";

import {
  DEMO_YOUTUBE_TITLE,
  DEMO_YOUTUBE_URL,
  backToHome,
  demoVerificationToken,
  demoYouTubeUrl,
  payForSubscription,
  randomEmail,
  readMembership,
  resolveOnHome,
  signUpAndSignIn,
  verifyEmailFromDemoInbox,
} from "./goldenPath";

/**
 * Golden path P2-09: free Quota exhausted → upgrade → email confirmed → unlimited Analysis,
 * plus the 抖音 branch of the same path while the feature switch is open.
 *
 * Everything a user does stays in the browser; the two things a test cannot click its way
 * through - reading the fake mailbox and paying on the hosted checkout page - go through
 * the very same endpoints the product exposes (see ``./goldenPath.ts``).
 *
 * Ordering note versus the ticket text: confirmation sits *before* the Quota burn, because
 * P2-06 puts the email gate in front of Analysis - an unverified Account never reaches the
 * 429 at all. The gate itself is asserted first, so the ordering is explicit either way.
 */
const enabled = process.env.PLAYWRIGHT_E2E === "1";

const SUMMARY_LINE = "间隔重复依据遗忘曲线安排复习：一天、三天，然后逐步拉长间隔。";
/** P2-08's conversion-aware copy for the two refusals (story 36/37). */
const QUOTA_SPENT = "今日 Quota 已用完，升级 VIP 后 Analysis 不限次。";
const EMAIL_UNVERIFIED = "请先验证邮箱后再发起 Analysis";

test.describe("golden path: quota exhausted → upgrade → unlimited Analysis", () => {
  test.skip(!enabled, "Set PLAYWRIGHT_E2E=1 to start both servers with fake adapters");

  test("free Quota runs out, the upgrade lands, Analysis stops being capped", async ({ page }) => {
    test.setTimeout(180_000);

    await page.goto("/");
    await resolveOnHome(page, DEMO_YOUTUBE_URL, DEMO_YOUTUBE_TITLE);

    const email = randomEmail();
    await page.getByRole("button", { name: "AI 分析" }).click();
    await expect(page).toHaveURL(/\/login\?next=/);
    await signUpAndSignIn(page, email);
    await expect(page).toHaveURL(/\/$/);

    // --- The gate in front of the free allowance (ticket #22) ----------------
    await page.getByRole("button", { name: "AI 分析" }).click();
    await expect(page.getByText(EMAIL_UNVERIFIED)).toBeVisible();

    await verifyEmailFromDemoInbox(page.request, email);

    // --- Free Quota: three Analyses ----------------------------------------
    for (const videoId of ["freeUnit001", "freeUnit002", "freeUnit003"]) {
      await resolveOnHome(page, demoYouTubeUrl(videoId), DEMO_YOUTUBE_TITLE);
      await page.getByRole("button", { name: "AI 分析" }).click();
      await expect(page).toHaveURL(/\/analyses\/[^/]+$/);
      await backToHome(page);
    }
    await page.getByRole("link", { name: "我的分析" }).click();
    await expect(page.getByText("Quota 剩余 0 / 3")).toBeVisible();

    // --- The fourth attempt is refused, in Quota words ----------------------
    await backToHome(page);
    await resolveOnHome(page, demoYouTubeUrl("unitFourOne"), DEMO_YOUTUBE_TITLE);
    await page.getByRole("button", { name: "AI 分析" }).click();
    await expect(page.getByText(QUOTA_SPENT)).toBeVisible();
    await expect(page).toHaveURL(/\/$/);

    // --- Upgrade: hosted checkout + injected payment success ----------------
    await payForSubscription(page.request, email);
    const membership = await readMembership(page.request, email);
    expect(membership).toMatchObject({ status: "active", is_vip: true });

    // --- Same address, now served ------------------------------------------
    await page.getByRole("button", { name: "AI 分析" }).click();
    await expect(page).toHaveURL(/\/analyses\/[^/]+$/);
    await expect(page.getByText(SUMMARY_LINE)).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText("已完成", { exact: true })).toBeVisible();
    await expect(page.getByRole("img", { name: "思维导图" })).toBeVisible({ timeout: 20_000 });
    // The cap is gone: no "剩余 x / 3", the unlimited label instead.
    await expect(page.getByText("Analysis 不限次").first()).toBeVisible();

    // --- And it stays gone: two more Analyses on the same day ---------------
    await backToHome(page);
    await resolveOnHome(page, demoYouTubeUrl("unitSix0001"), DEMO_YOUTUBE_TITLE);
    await page.getByRole("button", { name: "AI 分析" }).click();
    await expect(page).toHaveURL(/\/analyses\/[^/]+$/);
    await expect(page.getByText(SUMMARY_LINE)).toBeVisible({ timeout: 30_000 });

    await backToHome(page);
    await resolveOnHome(page, demoYouTubeUrl("seventhUnit"), DEMO_YOUTUBE_TITLE);
    await page.getByRole("button", { name: "AI 分析" }).click();
    await expect(page.getByText(SUMMARY_LINE)).toBeVisible({ timeout: 30_000 });

    // The subscriber's own history carries the Analyses this path produced, and the
    // allowance line still reads as uncapped.
    await page.getByRole("link", { name: "我的分析" }).click();
    await expect(page.getByText("Analysis 不限次").first()).toBeVisible();
    await expect(page.getByText(DEMO_YOUTUBE_TITLE).first()).toBeVisible();
  });

  test("抖音 parsing and Download while the feature switch is open", async ({ page }) => {
    await page.goto("/");

    await resolveOnHome(page, "https://www.douyin.com/video/7400123456789012345", "演示短视频：三分钟搞懂主动回忆");
    await expect(page.getByText("抖音")).toBeVisible();

    const subtitleDownload = page.waitForEvent("download");
    await page.getByRole("button", { name: "TXT", exact: true }).click();
    expect((await subtitleDownload).suggestedFilename()).toBe("douyin-7400123456789012345.txt");

    await page.getByRole("button", { name: "开始下载" }).click();
    await expect(page.getByRole("dialog", { name: "下载前请确认" })).toBeVisible();
    await page.getByRole("button", { name: "我已了解，继续下载" }).click();

    await expect(page.getByRole("link", { name: "保存文件" })).toBeVisible({ timeout: 20_000 });
    const mediaDownload = page.waitForEvent("download");
    await page.getByRole("link", { name: "保存文件" }).click();
    expect((await mediaDownload).suggestedFilename()).toMatch(/\.mp4$/);
  });

  test("conversion UI: verification page, upgrade CTA, pricing, checkout, account center", async ({ page }) => {
    test.setTimeout(180_000);

    await page.goto("/");
    await resolveOnHome(page, DEMO_YOUTUBE_URL, DEMO_YOUTUBE_TITLE);

    const email = randomEmail();
    await page.getByRole("button", { name: "AI 分析" }).click();
    await expect(page).toHaveURL(/\/login\?next=/);
    await signUpAndSignIn(page, email);

    // Unverified: the banner says what still works, and the 403 sells verification (36).
    await expect(page.getByText("邮箱尚未验证：视频解析与下载不受影响，但无法发起 Analysis。")).toBeVisible();
    await page.getByRole("button", { name: "AI 分析" }).click();
    await expect(page.getByText(EMAIL_UNVERIFIED)).toBeVisible();

    // The link inside the mail is a real page the browser can land on.
    const token = await demoVerificationToken(page.request, email);
    await page.goto(`/verify-email?token=${token}`);
    await expect(page.getByRole("heading", { name: "邮箱验证成功" })).toBeVisible();
    await page.getByRole("link", { name: "回到首页" }).click();
    await expect(page.getByText("邮箱尚未验证：视频解析与下载不受影响，但无法发起 Analysis。")).toBeHidden();

    // --- Burn the free allowance --------------------------------------------
    // Each create is awaited by its redirect to the Analysis screen: HomeView pushes
    // the route when the request lands, so leaving earlier lets a late reply yank the
    // page back mid-next-resolve.
    for (const videoId of ["uiFree00001", "uiFree00002", "uiFree00003"]) {
      await resolveOnHome(page, demoYouTubeUrl(videoId), DEMO_YOUTUBE_TITLE);
      await page.getByRole("button", { name: "AI 分析" }).click();
      await expect(page).toHaveURL(/\/analyses\/[^/]+$/);
      await backToHome(page);
    }

    // --- The 429 puts the upgrade offer right next to the refusal (story 37) -
    await resolveOnHome(page, demoYouTubeUrl("uiFourth001"), DEMO_YOUTUBE_TITLE);
    await page.getByRole("button", { name: "AI 分析" }).click();
    await expect(page.getByText(QUOTA_SPENT)).toBeVisible();
    await page.getByRole("link", { name: "升级 VIP，Analysis 不限次" }).click();
    await expect(page).toHaveURL(/\/pricing/);

    // One plan, one price (story 2).
    await expect(page.getByRole("heading", { name: "升级 VIP 会员" })).toBeVisible();
    await expect(page.getByText("$4.99/月")).toBeVisible();
    await expect(page.getByText("Analysis 不限次").first()).toBeVisible();

    // The browser leaves for the provider-hosted page (story 3). The demo gateway's
    // domain is stubbed rather than resolved: nothing in this run reaches the network,
    // and the point stands - the card data never lives on our pages.
    await page.route(/checkout\.demo\.invalid/, (route) =>
      route.fulfill({
        status: 200,
        contentType: "text/html; charset=utf-8",
        body: "<!doctype html><title>Demo Checkout</title><h1>演示结账页</h1>",
      }),
    );
    await page.getByRole("button", { name: "立即升级" }).click();
    await expect(page).toHaveURL(/checkout\.demo\.invalid\/cs_demo/);
    await expect(page.getByRole("heading", { name: "演示结账页" })).toBeVisible();

    await payForSubscription(page.request, email);

    // Back in the product: the return from the provider re-reads membership, and the
    // account center shows the subscription state next to the Quota (stories 4/35).
    await page.goto("/?checkout=success");
    await page.getByRole("link", { name: "个人中心" }).click();
    await expect(page).toHaveURL(/\/account/);
    await expect(page.getByText("VIP 订阅中")).toBeVisible();
    await expect(page.getByText("Analysis 不限次").first()).toBeVisible();

    // And Analysis really is uncapped.
    await backToHome(page);
    await resolveOnHome(page, demoYouTubeUrl("uiFifth0001"), DEMO_YOUTUBE_TITLE);
    await page.getByRole("button", { name: "AI 分析" }).click();
    await expect(page.getByText(SUMMARY_LINE)).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("img", { name: "思维导图" })).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText("Analysis 不限次").first()).toBeVisible();
  });
});
