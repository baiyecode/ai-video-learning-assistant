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

    // P3 Testing Decisions: besides H1s, TOC and console cleanliness, assert the
    // document title updates on every navigation — the runtime head contract.
    await page.goto("/features");
    await expect(page).toHaveTitle("功能：视频解析、字幕导出与 AI 分析 · AI 视频学习助手");
    await expect(page.getByRole("heading", { level: 1 })).toContainText("功能");

    await nav.getByRole("link", { name: "使用指南", exact: true }).click();
    await expect(page).toHaveURL(/\/guide$/);
    await expect(page).toHaveTitle("使用指南：解析、下载与 AI 分析 · AI 视频学习助手");
    await expect(page.getByRole("heading", { level: 1 })).toContainText("使用指南");
    await expect(page.getByRole("heading", { level: 2, name: "三步完成一次解析" })).toBeVisible();

    await nav.getByRole("link", { name: "FAQ", exact: true }).click();
    await expect(page).toHaveURL(/\/faq$/);
    await expect(page).toHaveTitle("常见问题：平台、Quota 与价格 · AI 视频学习助手");
    await expect(page.getByRole("heading", { level: 1 })).toContainText("常见问题");
    await expect(page.getByRole("heading", { level: 2, name: "支持哪些 Platform？" })).toBeVisible();

    await nav.getByRole("link", { name: "文章", exact: true }).click();
    await expect(page).toHaveURL(/\/articles$/);
    await expect(page).toHaveTitle("文章 · AI 视频学习助手");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("文章");

    await page.getByRole("link", { name: /B 站视频字幕怎么下载/ }).first().click();
    await expect(page).toHaveURL(/\/articles\/bilibili-subtitle-download$/);
    await expect(page).toHaveTitle(
      "B 站视频字幕怎么下载？SRT、VTT 与 TXT 导出步骤 · AI 视频学习助手",
    );
    await expect(page.getByRole("heading", { level: 1 })).toContainText("B 站视频字幕怎么下载");

    await nav.getByRole("link", { name: "首页", exact: true }).click();
    await expect(page).toHaveURL(/\/$/);
    await expect(page).toHaveTitle("视频下载、字幕导出与 AI 摘要 · AI 视频学习助手");
    await expect(page.getByRole("heading", { level: 1 })).toContainText("粘贴视频地址");

    expect(consoleErrors).toEqual([]);
  });
});

test.describe("article reading", () => {
  test.skip(!enabled, "Set PLAYWRIGHT_E2E=1 to start both servers with fake adapters");

  test("the detail page lists its sections and a TOC link scrolls to the anchor", async ({
    page,
  }) => {
    await page.goto("/articles/bilibili-subtitle-download");
    await expect(page.getByRole("heading", { level: 1 })).toContainText(
      "B 站视频字幕怎么下载",
    );

    const toc = page.getByRole("navigation", { name: "文章目录" });
    await expect(toc).toBeVisible();

    const sectionTitle = "SRT、VTT 与 TXT 怎么选";
    const sectionId = "srt-vtt-与-txt-怎么选";
    const target = page.locator(`h2[id="${sectionId}"]`);
    // The anchor the TOC points at exists in the rendered body.
    await expect(target).toHaveCount(1);

    await toc.getByRole("link", { name: sectionTitle, exact: true }).click();

    // The browser moved to the anchor: the URL carries the hash and the heading
    // was scrolled into view.
    await expect(page).toHaveURL(/#.+/);
    const hash = await page.evaluate(() => decodeURIComponent(window.location.hash));
    expect(hash).toBe(`#${sectionId}`);
    await expect
      .poll(() => page.evaluate(() => window.scrollY))
      .toBeGreaterThan(0);
    await expect
      .poll(() =>
        target.evaluate((element) => element.getBoundingClientRect().top),
      )
      .toBeLessThan(400);
  });
});

test.describe("private routes", () => {
  test.skip(!enabled, "Set PLAYWRIGHT_E2E=1 to start both servers with fake adapters");

  test("login and verify-email stay noindex, and /account bounces to login", async ({ page }) => {
    for (const route of ["/login", "/verify-email"]) {
      await page.goto(route);
      await expect(page.locator('meta[name="robots"]')).toHaveAttribute(
        "content",
        "noindex,nofollow",
      );
    }

    await page.goto("/account");
    await expect(page).toHaveURL(/\/login\?next=/);
    await expect(page.locator('meta[name="robots"]')).toHaveAttribute(
      "content",
      "noindex,nofollow",
    );
  });

  test("an unknown path and an unknown Article slug render the same 404 page", async ({
    page,
  }) => {
    for (const route of ["/definitely-not-a-page", "/articles/definitely-not-a-page"]) {
      await page.goto(route);
      await expect(page.getByRole("heading", { level: 1 })).toHaveText("页面不存在");
      await expect(page.locator('meta[name="robots"]')).toHaveAttribute(
        "content",
        "noindex,nofollow",
      );
    }
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
