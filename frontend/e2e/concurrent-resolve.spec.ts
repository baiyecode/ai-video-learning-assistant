import { expect, test, type Page, type Response } from "@playwright/test";

import { DEMO_YOUTUBE_TITLE, demoYouTubeUrl } from "./goldenPath";

/**
 * Regression for the empty-database resolve race (tickets #51/#52/#54/#56).
 *
 * Two independent browser contexts, on the same SPA, resolve the *same brand-new*
 * Video at the same moment. Before #54 both requests read "no Subtitle yet" and the
 * losing side inserted a second `subtitles.video_id` row, answering 500; the Playwright
 * config used to hide this with `workers: 1`. This spec runs as its own file, so once
 * files run in parallel (see playwright.config.ts) it genuinely competes for the shared
 * fake-adapter backend and SQLite file with the other specs.
 *
 * The platform video id is generated per run, so the row is new even if a crashed run
 * left something behind. YouTube ids are exactly 11 characters of `[A-Za-z0-9_-]`.
 */
const enabled = process.env.PLAYWRIGHT_E2E === "1";

const SUBTITLE_LINE = "间隔重复是一种利用遗忘曲线安排复习的学习方法。";

function runUniqueVideoId(): string {
  // `c` + 6 base-36 ticks + 4 base-36 random chars = the 11 characters a YouTube id has.
  const random = Math.random().toString(36).slice(2, 6).padEnd(4, "0");
  return `c${Date.now().toString(36).slice(-6)}${random}`;
}

function isResolveResponse(response: Response): boolean {
  return (
    response.request().method() === "POST" &&
    new URL(response.url()).pathname === "/api/videos/resolve"
  );
}

async function openHome(page: Page, url: string): Promise<void> {
  await page.goto("/");
  await page.getByLabel("页面地址").fill(url);
}

test.describe("concurrent resolve", () => {
  test.skip(!enabled, "Set PLAYWRIGHT_E2E=1 to start both servers with fake adapters");

  test("two browser contexts resolve one brand-new Video at the same time", async ({ browser }) => {
    const platformVideoId = runUniqueVideoId();
    const videoUrl = demoYouTubeUrl(platformVideoId);

    const firstContext = await browser.newContext();
    const secondContext = await browser.newContext();
    try {
      const firstPage = await firstContext.newPage();
      const secondPage = await secondContext.newPage();

      // Both pages are ready before either request starts: the race is the point.
      await Promise.all([openHome(firstPage, videoUrl), openHome(secondPage, videoUrl)]);

      const firstResponse = firstPage.waitForResponse(isResolveResponse);
      const secondResponse = secondPage.waitForResponse(isResolveResponse);
      await Promise.all([
        firstPage.getByRole("button", { name: "解析视频" }).click(),
        secondPage.getByRole("button", { name: "解析视频" }).click(),
      ]);

      const [firstResolve, secondResolve] = await Promise.all([firstResponse, secondResponse]);

      // Both sides must succeed, and both must name the one Video row they raced on.
      expect(firstResolve.status(), await firstResolve.text()).toBe(200);
      expect(secondResolve.status(), await secondResolve.text()).toBe(200);
      const firstBody = (await firstResolve.json()) as {
        video: { id: string; platform_video_id: string };
      };
      const secondBody = (await secondResolve.json()) as {
        video: { id: string; platform_video_id: string };
      };
      expect(firstBody.video.platform_video_id).toBe(platformVideoId);
      expect(secondBody.video.platform_video_id).toBe(platformVideoId);
      expect(firstBody.video.id).toBeTruthy();
      expect(secondBody.video.id).toBe(firstBody.video.id);

      // ... and both users see the resolved Video on their own page.
      for (const page of [firstPage, secondPage]) {
        await expect(
          page.getByRole("heading", { level: 2, name: DEMO_YOUTUBE_TITLE }),
        ).toBeVisible();
        await expect(page.getByText(SUBTITLE_LINE)).toBeVisible();
      }
    } finally {
      await firstContext.close();
      await secondContext.close();
    }
  });
});
