import { expect, test } from "@playwright/test";

/**
 * Golden path skeleton: Visitor resolve → Download → login → Analysis → export Subtitle.
 *
 * Kept skipped by default: it needs both dev servers running with fake adapters (see
 * README). Later tickets extend the steps without adding another e2e scenario.
 */
const enabled = process.env.PLAYWRIGHT_E2E === "1";

test.describe("golden path", () => {
  test.skip(!enabled, "Set PLAYWRIGHT_E2E=1 with backend + frontend running (see README)");

  test("home page exposes the resolve entry point and legal notice", async ({ page }) => {
    await page.goto("/");

    await expect(page.getByRole("heading", { level: 1 })).toContainText("粘贴视频链接");
    await expect(page.getByLabel("视频链接")).toBeVisible();
    await expect(page.getByText("仅限个人备份或已获授权内容")).toBeVisible();

    // TODO ticket #3: submit a fake video URL and assert the resolved metadata.
    // TODO ticket #5: start a Download and wait for it to become ready.
    // TODO ticket #7/#8: log in, start an Analysis, assert streaming summary + mindmap.
    // TODO ticket #4: export the Subtitle.
  });
});
