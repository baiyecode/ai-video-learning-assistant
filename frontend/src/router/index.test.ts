// @vitest-environment jsdom
/**
 * Client navigation uses the same descriptors as the build: no route-specific
 * title/robots code in the router, and no accumulated managed tags.
 */
import { createMemoryHistory } from "vue-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createAppRouter } from "@/router";

afterEach(() => {
  vi.unstubAllEnvs();
  document.head.innerHTML = "";
});

describe("router head updates", () => {
  it("updates title, description and canonical from the shared descriptor", async () => {
    vi.stubEnv("VITE_SITE_ORIGIN", "https://example.com");
    const router = createAppRouter(createMemoryHistory());

    await router.push("/features");
    await router.isReady();

    expect(document.title).toBe("功能：视频解析、字幕导出与 AI 分析 · AI 视频学习助手");
    expect(document.querySelector('meta[name="description"]')?.getAttribute("content")?.length).toBeGreaterThanOrEqual(70);
    expect(document.querySelector('link[rel="canonical"]')?.getAttribute("href")).toBe(
      "https://example.com/features",
    );

    await router.push("/");
    expect(document.title).toBe("视频下载与 AI 分析 · AI 视频学习助手");
    expect(document.querySelector('link[rel="canonical"]')?.getAttribute("href")).toBe(
      "https://example.com/",
    );
  });

  it("does not duplicate managed tags after repeated navigation", async () => {
    vi.stubEnv("VITE_SITE_ORIGIN", "https://example.com");
    const router = createAppRouter(createMemoryHistory());

    await router.push("/features");
    await router.push("/");
    await router.push("/features");
    await router.isReady();

    expect(document.querySelectorAll("title")).toHaveLength(1);
    expect(document.querySelectorAll('link[rel="canonical"]')).toHaveLength(1);
    expect(document.querySelectorAll('meta[name="robots"]')).toHaveLength(1);
    expect(document.querySelectorAll('script[type="application/ld+json"]')).toHaveLength(1);
  });
});
