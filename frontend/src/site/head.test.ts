// @vitest-environment jsdom
/**
 * Runtime head contract: every managed tag is replaced, never appended, so
 * client navigation cannot leave duplicate canonical/OG/JSON-LD behind.
 */
import { beforeEach, describe, expect, it } from "vitest";

import { applyHead } from "@/site/head";
import { descriptorForRoute } from "@/site/seo";

const ORIGIN = "https://example.com";

beforeEach(() => {
  document.head.innerHTML =
    '<title>AI 视频学习助手</title><meta name="description" content="shell description" />';
  document.body.innerHTML = "";
});

describe("applyHead", () => {
  it("replaces the shell title and inserts the public page tags", () => {
    applyHead(descriptorForRoute("features"), ORIGIN, document);

    expect(document.title).toBe("功能：视频解析、字幕导出与 AI 分析 · AI 视频学习助手");
    expect(document.querySelectorAll("title")).toHaveLength(1);
    expect(document.querySelector('link[rel="canonical"]')?.getAttribute("href")).toBe(
      "https://example.com/features",
    );
    expect(document.querySelector('meta[name="robots"]')?.getAttribute("content")).toBe(
      "index,follow,max-image-preview:large",
    );
    expect(document.querySelectorAll('meta[property^="og:"]').length).toBeGreaterThanOrEqual(9);
    expect(document.querySelectorAll('script[type="application/ld+json"]')).toHaveLength(1);
  });

  it("removes every previously managed tag on navigation", () => {
    applyHead(descriptorForRoute("home"), ORIGIN, document);
    applyHead(descriptorForRoute("features"), ORIGIN, document);
    applyHead(descriptorForRoute("home"), ORIGIN, document);
    applyHead(descriptorForRoute("features"), ORIGIN, document);

    expect(document.title).toBe("功能：视频解析、字幕导出与 AI 分析 · AI 视频学习助手");
    expect(document.querySelectorAll("title")).toHaveLength(1);
    expect(document.querySelectorAll('meta[name="description"]')).toHaveLength(1);
    expect(document.querySelectorAll('link[rel="canonical"]')).toHaveLength(1);
    expect(document.querySelector('link[rel="canonical"]')?.getAttribute("href")).toBe(
      "https://example.com/features",
    );
    expect(document.querySelectorAll('meta[name="robots"]')).toHaveLength(1);
    expect(document.querySelectorAll('meta[property="og:url"]')).toHaveLength(1);
    expect(document.querySelectorAll('meta[name="twitter:card"]')).toHaveLength(1);
    expect(document.querySelectorAll('script[type="application/ld+json"]')).toHaveLength(1);
  });

  it("switches private pages to noindex and drops public-only tags", () => {
    applyHead(descriptorForRoute("features"), ORIGIN, document);
    applyHead(descriptorForRoute("account"), ORIGIN, document);

    expect(document.querySelector('meta[name="robots"]')?.getAttribute("content")).toBe("noindex,nofollow");
    expect(document.querySelectorAll("title")).toHaveLength(1);
    expect(document.title).toBe("个人中心 · AI 视频学习助手");
    expect(document.querySelectorAll('link[rel="canonical"]')).toHaveLength(0);
    expect(document.querySelectorAll('meta[property^="og:"]')).toHaveLength(0);
    expect(document.querySelectorAll('script[type="application/ld+json"]')).toHaveLength(0);
  });

  it("falls back to the noindex not-found descriptor for unknown routes", () => {
    applyHead(descriptorForRoute("does-not-exist"), ORIGIN, document);

    expect(document.title).toBe("页面不存在 · AI 视频学习助手");
    expect(document.querySelector('meta[name="robots"]')?.getAttribute("content")).toBe("noindex,nofollow");
  });
});
