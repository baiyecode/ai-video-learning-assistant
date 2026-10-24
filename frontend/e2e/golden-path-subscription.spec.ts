import { expect, test } from "@playwright/test";

import {
  DEMO_YOUTUBE_TITLE,
  DEMO_YOUTUBE_URL,
  backToHome,
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
 * Everything a user does stays in the browser; only the fake mailbox read, the hosted
 * checkout and the payment-success webhook run over HTTP against the same endpoints the
 * product exposes (see ``./goldenPath.ts``).
 *
 * Ordering note versus the ticket text: confirmation sits *before* the Quota burn,
 * because P2-06 puts the email gate in front of Analysis - an unverified Account cannot
 * reach the 429 at all. The gate itself is asserted first so the ordering is explicit.
 */
const enabled = process.env.PLAYWRIGHT_E2E === "1";

/**
 * Ticket P2-08's conversion UI (定价页 / 升级 CTA / 个人中心 / ``/verify-email``) is a
 * sibling ticket; until it lands the chain above covers the same outcomes. Set
 * ``PLAYWRIGHT_CONVERSION_UI=1`` to run the UI-driven version once it exists.
 */
const conversionUi = process.env.PLAYWRIGHT_CONVERSION_UI === "1";

const SUMMARY_LINE = "间隔重复依据遗忘曲线安排复习：一天、三天，然后逐步拉长间隔。";

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
    await expect(page.getByText("请先验证邮箱后再发起 Analysis")).toBeVisible();

    await verifyEmailFromDemoInbox(page.request, email);

    // --- Free Quota: three Analyses ----------------------------------------
    for (const videoId of ["freeUnit001", "freeUnit002", "freeUnit003"]) {
      await resolveOnHome(page, demoYouTubeUrl(videoId), DEMO_YOUTUBE_TITLE);
      await page.getByRole("button", { name: "AI 分析" }).click();
      await expect(page).toHaveURL(/\/analyses\/[^/]+$/);
      await backToHome(page);
    }
    // The third result still reads as a paid-for-allowance free Account.
    await page.getByRole("link", { name: "我的分析" }).click();
    await expect(page.getByText("Quota 剩余 0 / 3")).toBeVisible();

    // --- The fourth attempt is refused, in Quota words ----------------------
    await backToHome(page);
    await resolveOnHome(page, demoYouTubeUrl("unitFourOne"), DEMO_YOUTUBE_TITLE);
    await page.getByRole("button", { name: "AI 分析" }).click();
    await expect(page.getByText(/今日 Analysis Quota 已用完/)).toBeVisible();
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
    await expect(page.getByText("Analysis 不限次")).toBeVisible();

    // --- And it stays gone: a fourth and fifth Analysis on the same day ------
    await backToHome(page);
    await resolveOnHome(page, demoYouTubeUrl("unitSix0001"), DEMO_YOUTUBE_TITLE);
    await page.getByRole("button", { name: "AI 分析" }).click();
    await expect(page).toHaveURL(/\/analyses\/[^/]+$/);
    await expect(page.getByText(SUMMARY_LINE)).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText("Analysis 不限次")).toBeVisible();

    await backToHome(page);
    await resolveOnHome(page, demoYouTubeUrl("seventhUnit"), DEMO_YOUTUBE_TITLE);
    await page.getByRole("button", { name: "AI 分析" }).click();
    await expect(page.getByText(SUMMARY_LINE)).toBeVisible({ timeout: 30_000 });

    // The subscriber's own history carries the Analyses this path produced, and the
    // allowance line still reads as uncapped.
    await page.getByRole("link", { name: "我的分析" }).click();
    await expect(page.getByText("Analysis 不限次")).toBeVisible();
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

  test.describe("conversion UI chain (ticket P2-08)", () => {
    test.skip(!conversionUi, "Awaiting ticket P2-08: 定价页 / 升级 CTA / 个人中心 / /verify-email");

    test("upgrade CTA, hosted checkout, subscription status in the account center", async ({ page }) => {
      test.setTimeout(180_000);

      await page.goto("/");
      await resolveOnHome(page, DEMO_YOUTUBE_URL, DEMO_YOUTUBE_TITLE);

      const email = randomEmail();
      await page.getByRole("button", { name: "AI 分析" }).click();
      await expect(page).toHaveURL(/\/login\?next=/);
      await signUpAndSignIn(page, email);

      // The unverified banner points at the mail; the link in that mail is a real page.
      await expect(page.getByText(/验证邮箱/)).toBeVisible();
      const inbox = await page.request.get(`/api/demo/inbox?to=${encodeURIComponent(email)}`);
      const token = ((await inbox.json()) as { verification_token: string | null }[])[0].verification_token;
      await page.goto(`/verify-email?token=${token}`);
      await expect(page.getByText(/验证成功|已验证/)).toBeVisible();

      // Burn the free allowance, then take the CTA the 429 puts in front of the user.
      for (const videoId of ["uiFree00001", "uiFree00002", "uiFree00003"]) {
        await resolveOnHome(page, demoYouTubeUrl(videoId), DEMO_YOUTUBE_TITLE);
        await page.getByRole("button", { name: "AI 分析" }).click();
        await backToHome(page);
      }
      await resolveOnHome(page, demoYouTubeUrl("uiFourth001"), DEMO_YOUTUBE_TITLE);
      await page.getByRole("button", { name: "AI 分析" }).click();
      await expect(page.getByText(/今日 Analysis Quota 已用完/)).toBeVisible();

      await page.getByRole("link", { name: /升级/ }).click();
      await expect(page).toHaveURL(/\/pricing/);
      await expect(page.getByText("$4.99/月")).toBeVisible();
      await expect(page.getByText("Analysis 不限次")).toBeVisible();

      await page.getByRole("button", { name: /升级到 VIP|立即升级/ }).click();
      // The fake gateway's hosted page: the browser leaves for the checkout URL.
      await expect(page).toHaveURL(/checkout\.demo\.invalid/);
      await payForSubscription(page.request, email);

      // Back in the product: the checkout redirect and the account center agree.
      await page.goto("/?checkout=success");
      await page.goto("/account");
      await expect(page.getByText(/VIP|订阅生效|生效中/)).toBeVisible();
      await expect(page.getByText("Analysis 不限次")).toBeVisible();

      await resolveOnHome(page, demoYouTubeUrl("uiFifth0001"), DEMO_YOUTUBE_TITLE);
      await page.getByRole("button", { name: "AI 分析" }).click();
      await expect(page.getByText(SUMMARY_LINE)).toBeVisible({ timeout: 30_000 });
      await expect(page.getByRole("img", { name: "思维导图" })).toBeVisible({ timeout: 20_000 });
    });
  });
});
