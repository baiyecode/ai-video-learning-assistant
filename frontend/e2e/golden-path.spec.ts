import { expect, test } from "@playwright/test";

import {
  DEMO_YOUTUBE_TITLE,
  DEMO_YOUTUBE_URL,
  randomEmail,
  signUpAndSignIn,
  verifyEmailFromDemoInbox,
} from "./goldenPath";

/**
 * Golden path: Visitor resolve → Subtitle export → Download → register → sign in →
 * email confirmation → Analysis → mindmap.
 *
 * Requires deterministic adapters; `PLAYWRIGHT_E2E=1` makes Playwright start both
 * servers (see playwright.config.ts). Every run registers a fresh Account.
 *
 * P2-06 (ticket #22) split registration from sign-in and put email confirmation in
 * front of Analysis, so this path now reads the verification link out of the fake
 * mailbox instead of assuming a session the server never handed out.
 */
const enabled = process.env.PLAYWRIGHT_E2E === "1";

const VIDEO_URL = DEMO_YOUTUBE_URL;
const VIDEO_TITLE = DEMO_YOUTUBE_TITLE;

test.describe("golden path", () => {
  test.skip(!enabled, "Set PLAYWRIGHT_E2E=1 to start both servers with fake adapters");

  test("resolve, export Subtitle, Download, then register, confirm and generate an Analysis", async ({
    page,
  }) => {
    await page.goto("/");

    await expect(page.getByRole("heading", { level: 1 })).toContainText("粘贴视频地址");
    await expect(page.getByLabel("视频地址")).toBeVisible();
    await expect(
      page.getByText("仅限个人备份或已获授权内容，不支持播放列表、直播与 DRM 内容。"),
    ).toBeVisible();

    // --- Visitor: resolve ---------------------------------------------------
    await page.getByLabel("视频地址").fill(VIDEO_URL);
    await page.getByRole("button", { name: "解析视频" }).click();

    await expect(page.getByRole("heading", { level: 2, name: VIDEO_TITLE })).toBeVisible();
    await expect(
      page.getByText("间隔重复是一种利用遗忘曲线安排复习的学习方法。"),
    ).toBeVisible();

    // --- Visitor: export the Subtitle --------------------------------------
    const subtitleDownload = page.waitForEvent("download");
    await page.getByRole("button", { name: "TXT", exact: true }).click();
    expect((await subtitleDownload).suggestedFilename()).toBe("youtube-demoP1Video.txt");

    // --- Visitor: server-proxied Download ----------------------------------
    await page.getByRole("button", { name: "开始下载" }).click();
    await expect(page.getByRole("dialog", { name: "下载前请确认" })).toBeVisible();
    await page.getByRole("button", { name: "我已了解，继续下载" }).click();

    await expect(page.getByRole("link", { name: "保存文件" })).toBeVisible({ timeout: 20_000 });
    const mediaDownload = page.waitForEvent("download");
    await page.getByRole("link", { name: "保存文件" }).click();
    expect((await mediaDownload).suggestedFilename()).toMatch(/\.mp4$/);

    // --- Account: the Analysis button funnels into registration -------------
    await page.getByRole("button", { name: "AI 分析" }).click();
    await expect(page).toHaveURL(/\/login\?next=/);

    const email = randomEmail();
    await signUpAndSignIn(page, email);

    // Back on the preserved resolve result.
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByRole("heading", { level: 2, name: VIDEO_TITLE })).toBeVisible();

    // --- Account: Analysis waits for the confirmed email (ticket #22) -------
    await page.getByRole("button", { name: "AI 分析" }).click();
    await expect(page.getByText("请先验证邮箱后再发起 Analysis")).toBeVisible();

    await verifyEmailFromDemoInbox(page.request, email);

    // --- Account: create and stream the Analysis ---------------------------
    await page.getByRole("button", { name: "AI 分析" }).click();
    await expect(page).toHaveURL(/\/analyses\/[^/]+$/);

    await expect(page.getByText("间隔重复依据遗忘曲线安排复习：一天、三天，然后逐步拉长间隔。")).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.getByText("已完成", { exact: true })).toBeVisible();

    // Mindmap rendered from the final Markdown block.
    await expect(page.getByRole("heading", { name: "思维导图" })).toBeVisible();
    await expect(page.getByRole("img", { name: "思维导图" })).toBeVisible({ timeout: 20_000 });
    await expect(page.getByRole("button", { name: "导出 SVG" })).toBeEnabled();

    // The fresh Account has used one of its three daily Quota units.
    await expect(page.getByText("Quota 剩余 2 / 3")).toBeVisible();

    // ADR-0005: private Analysis pages are never indexed.
    await expect(page.locator('meta[name="robots"]')).toHaveAttribute("content", "noindex,nofollow");
  });
});
