import { expect, test } from "@playwright/test";

import { DEMO_YOUTUBE_TITLE, DEMO_YOUTUBE_URL, resolveOnHome } from "./goldenPath";

/**
 * Marketing surface regressions: the home tool keeps the spotlight after a
 * resolve, the new public pages link together, and the navigation fits a phone.
 *
 * The static artifacts are covered by ``src/site/marketing-pages.test.ts``; this
 * spec only exercises the SPA behaviour (v-if on the home marketing block,
 * client-side navigation and narrow-viewport layout).
 */
const enabled = process.env.PLAYWRIGHT_E2E === "1";

test.describe("home marketing sections", () => {
  test.skip(!enabled, "Set PLAYWRIGHT_E2E=1 to start both servers with fake adapters");

  test("hide once a Video resolves and come back on a fresh home visit", async ({ page }) => {
    await page.goto("/");

    const valueProp = page.getByRole("heading", {
      level: 2,
      name: "把公开视频变成可用的学习材料",
    });
    const steps = page.getByRole("heading", { level: 2, name: "三步完成一次解析" });
    await expect(valueProp).toBeVisible();
    await expect(steps).toBeVisible();

    await resolveOnHome(page, DEMO_YOUTUBE_URL, DEMO_YOUTUBE_TITLE);

    await expect(valueProp).toBeHidden();
    await expect(steps).toBeHidden();
    await expect(page.getByRole("heading", { level: 2, name: DEMO_YOUTUBE_TITLE })).toBeVisible();

    // The marketing surface returns when the tool no longer has a result.
    await page.getByRole("link", { name: "AI 视频学习助手" }).click();
    await page.reload();
    await expect(valueProp).toBeVisible();
  });
});

test.describe("static navigation", () => {
  test.skip(!enabled, "Set PLAYWRIGHT_E2E=1 to start both servers with fake adapters");

  test("features → guide → FAQ → articles → article → home", async ({ page }) => {
    const consoleErrors: string[] = [];
    page.on("console", (message) => {
      // The anonymous Session bootstrap always probes ``/auth/refresh`` and logs
      // that expected 401; everything else is a real regression.
      if (message.type() === "error" && !/401 \(Unauthorized\)/.test(message.text())) {
        consoleErrors.push(message.text());
      }
    });
    page.on("pageerror", (error) => consoleErrors.push(error.message));

    const nav = page.getByRole("navigation", { name: "主导航" });

    await page.goto("/features");
    await expect(page.getByRole("heading", { level: 1 })).toContainText("功能");

    await nav.getByRole("link", { name: "使用指南", exact: true }).click();
    await expect(page).toHaveURL(/\/guide$/);
    await expect(page.getByRole("heading", { level: 1 })).toContainText("使用指南");
    await expect(page.getByRole("heading", { level: 2, name: "三步完成一次解析" })).toBeVisible();

    await nav.getByRole("link", { name: "FAQ", exact: true }).click();
    await expect(page).toHaveURL(/\/faq$/);
    await expect(page.getByRole("heading", { level: 1 })).toContainText("常见问题");
    await expect(page.getByRole("heading", { level: 2, name: "支持哪些 Platform？" })).toBeVisible();

    await nav.getByRole("link", { name: "文章", exact: true }).click();
    await expect(page).toHaveURL(/\/articles$/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("文章");

    await page.getByRole("link", { name: /B 站视频字幕怎么下载/ }).first().click();
    await expect(page).toHaveURL(/\/articles\/bilibili-subtitle-download$/);
    await expect(page.getByRole("heading", { level: 1 })).toContainText("B 站视频字幕怎么下载");

    await nav.getByRole("link", { name: "首页", exact: true }).click();
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByRole("heading", { level: 1 })).toContainText("粘贴视频地址");

    expect(consoleErrors).toEqual([]);
  });
});

test.describe("mobile layout", () => {
  test.skip(!enabled, "Set PLAYWRIGHT_E2E=1 to start both servers with fake adapters");
  test.use({ viewport: { width: 375, height: 800 } });

  test("home and FAQ never scroll horizontally at 375px", async ({ page }) => {
    for (const route of ["/", "/faq"]) {
      await page.goto(route);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth,
      );
      expect(overflow, `${route} scrolls horizontally by ${overflow}px`).toBeLessThanOrEqual(1);
    }
  });
});
