/**
 * Discovery artifacts through the single build seam: a temp directory receives
 * sitemap.xml, robots.txt and llms.txt built from the same descriptors and
 * Article collection the public pages use. No network, no Vite build.
 */
import { readFile, stat } from "node:fs/promises";
import path from "node:path";

import { describe, expect, it, vi } from "vitest";

import { buildSite } from "@/site/build-site";
import { buildRobotsTxt } from "@/site/discovery";
import { renderRoute } from "@/site/entry-server";
import { defaultArticleSources } from "@/site/article-sources";
import type { ArticleSource } from "@/site/articles";
import { pageDescriptors } from "@/site/seo";
import { SHELL, useTempDirs } from "@/site/test-support";

const ORIGIN = "https://example.com";

const PUBLIC_URLS = [
  `${ORIGIN}/`,
  `${ORIGIN}/features`,
  `${ORIGIN}/guide`,
  `${ORIGIN}/faq`,
  `${ORIGIN}/pricing`,
  `${ORIGIN}/terms`,
  `${ORIGIN}/articles`,
  `${ORIGIN}/articles/bilibili-subtitle-download`,
  `${ORIGIN}/articles/youtube-study-notes`,
  `${ORIGIN}/articles/ai-video-summary-mindmap`,
  `${ORIGIN}/articles/douyin-video-parsing`,
];

const ARTICLE_LASTMOD: Record<string, string> = {
  "/articles/bilibili-subtitle-download": "2026-10-25",
  "/articles/youtube-study-notes": "2026-10-24",
  "/articles/ai-video-summary-mindmap": "2026-10-23",
  "/articles/douyin-video-parsing": "2026-10-22",
};

const tempDir = useTempDirs("seo-discovery-");

async function build(outDir: string, overrides?: Partial<Parameters<typeof buildSite>[0]>) {
  return buildSite({
    origin: ORIGIN,
    descriptors: pageDescriptors,
    shellHtml: SHELL,
    outputDir: outDir,
    renderRoute,
    ...overrides,
  });
}

function sitemapEntries(xml: string): { loc: string; lastmod?: string }[] {
  return [...xml.matchAll(/<url>([\s\S]*?)<\/url>/g)].map((block) => {
    const body = block[1];
    const loc = /<loc>([^<]+)<\/loc>/.exec(body)?.[1] ?? "";
    const lastmod = /<lastmod>([^<]+)<\/lastmod>/.exec(body)?.[1];
    return lastmod ? { loc, lastmod } : { loc };
  });
}

/** Cheap renderer for the collection-focused builds: no Vue, but real anchors. */
function placeholderRoute(routePath: string): { html: string } {
  if (routePath === "/terms") return { html: '<h1>使用条款</h1><section id="report"></section>' };
  return { html: "<h1>占位页面</h1>" };
}

function draftSource(): ArticleSource {
  const body = "这是一段用于测试草稿排除的文章正文，包含足够多的字符以便通过构建期长度校验。".repeat(25);
  return {
    fileName: "draft-article.md",
    source: [
      "---",
      "title: 草稿：不应出现在站点的测试文章",
      "description: 这是一段用于测试草稿排除的文章描述，覆盖七十到一百六十个字符的长度要求，确保描述足够详细；草稿不应进入 sitemap、llms.txt 或任何公开页面。",
      "published: 2026-10-01",
      "draft: true",
      "---",
      "",
      body,
      "",
    ].join("\n"),
  };
}

describe("sitemap.xml", () => {
  it("is well-formed XML listing every public canonical exactly once", async () => {
    const outDir = await tempDir();

    await build(outDir);

    const xml = await readFile(path.join(outDir, "sitemap.xml"), "utf8");
    expect(xml.startsWith('<?xml version="1.0" encoding="UTF-8"?>')).toBe(true);
    expect(xml).toContain('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">');
    expect(xml.trimEnd().endsWith("</urlset>")).toBe(true);

    const entries = sitemapEntries(xml);
    expect(entries.map((entry) => entry.loc)).toEqual(PUBLIC_URLS);
    expect(new Set(entries.map((entry) => entry.loc)).size).toBe(PUBLIC_URLS.length);
    for (const entry of entries) {
      expect(entry.loc.startsWith(`${ORIGIN}/`)).toBe(true);
    }
    // Home keeps the origin-root form; other canonical URLs have no trailing slash.
    expect(entries[0].loc).toBe(`${ORIGIN}/`);
    expect(entries.slice(1).every((entry) => !entry.loc.endsWith("/"))).toBe(true);
  });

  it("uses frontmatter updated (else published) as the Article lastmod", async () => {
    const outDir = await tempDir();

    await build(outDir);

    const entries = sitemapEntries(await readFile(path.join(outDir, "sitemap.xml"), "utf8"));
    const lastmods = Object.fromEntries(
      entries.filter((entry) => entry.lastmod).map((entry) => [entry.loc, entry.lastmod]),
    );
    expect(Object.keys(lastmods).sort()).toEqual(
      Object.keys(ARTICLE_LASTMOD)
        .map((route) => `${ORIGIN}${route}`)
        .sort(),
    );
    for (const [route, date] of Object.entries(ARTICLE_LASTMOD)) {
      expect(lastmods[`${ORIGIN}${route}`]).toBe(date);
    }
    // Non-article pages carry no invented lastmod.
    const home = entries.find((entry) => entry.loc === `${ORIGIN}/`);
    expect(home?.lastmod).toBeUndefined();
  });

  it("uses frontmatter updated when it differs from published", async () => {
    const outDir = await tempDir();
    const source: ArticleSource = {
      fileName: "updated-article.md",
      source: [
        "---",
        "title: 更新日期测试文章",
        "description: 这是一篇用于验证 sitemap lastmod 取 frontmatter updated 的测试文章，描述长度需要落在七十到一百六十个字符之间，以便通过构建期内容校验。",
        "published: 2026-10-01",
        "updated: 2026-10-20",
        "---",
        "",
        "这是一段用于验证更新日期的文章正文，包含足够多的字符以便通过构建期的长度校验。".repeat(25),
        "",
      ].join("\n"),
    };

    await build(outDir, {
      articleSources: [...defaultArticleSources, source],
      renderRoute: placeholderRoute,
    });

    const entries = sitemapEntries(await readFile(path.join(outDir, "sitemap.xml"), "utf8"));
    const entry = entries.find((item) => item.loc === `${ORIGIN}/articles/updated-article`);
    expect(entry?.lastmod).toBe("2026-10-20");
  });

  it("excludes private routes, 404, app.html and drafts", async () => {
    const outDir = await tempDir();

    await build(outDir, {
      articleSources: [...defaultArticleSources, draftSource()],
      renderRoute: placeholderRoute,
    });

    const xml = await readFile(path.join(outDir, "sitemap.xml"), "utf8");
    for (const excluded of ["/login", "/account", "/analyses", "/verify-email", "/app.html", "/404", "draft-article"]) {
      expect(xml).not.toContain(excluded);
    }
    expect(sitemapEntries(xml)).toHaveLength(PUBLIC_URLS.length);
    await expect(stat(path.join(outDir, "articles", "draft-article.html"))).rejects.toThrow();
  });
});

describe("robots.txt", () => {
  it("points at the sitemap and disallows the private paths for a public origin", async () => {
    const outDir = await tempDir();

    await build(outDir);

    const robots = await readFile(path.join(outDir, "robots.txt"), "utf8");
    expect(robots).toBe(
      [
        "User-agent: *",
        "Allow: /",
        "Disallow: /api/",
        "Disallow: /login",
        "Disallow: /account",
        "Disallow: /analyses",
        "Disallow: /verify-email",
        "Disallow: /app.html",
        "",
        `Sitemap: ${ORIGIN}/sitemap.xml`,
        "",
      ].join("\n"),
    );
  });

  it("disallows everything and warns when the origin is loopback", async () => {
    const outDir = await tempDir();
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});

    await build(outDir, { origin: "http://localhost:8080" });

    const robots = await readFile(path.join(outDir, "robots.txt"), "utf8");
    const lines = robots.split("\n");
    expect(lines).toContain("User-agent: *");
    expect(lines).toContain("Disallow: /");
    expect(lines).not.toContain("Allow: /");
    expect(lines).toContain("Sitemap: http://localhost:8080/sitemap.xml");
    expect(robots).not.toContain("/api/");
    expect(warn).toHaveBeenCalled();
    expect(warn.mock.calls.flat().join(" ")).toMatch(/loopback/i);
  });

  it("treats every loopback host form as non-indexable", () => {
    for (const origin of [
      "http://localhost:5173",
      "http://localhost",
      "http://app.localhost:8080",
      "http://127.0.0.1:8080",
      "http://127.0.0.2",
      "http://127.255.255.254:9000",
      "http://0.0.0.0:8080",
      "http://[::1]:8080",
    ]) {
      const lines = buildRobotsTxt(origin).split("\n");
      expect(lines, origin).toContain("Disallow: /");
      expect(lines, origin).not.toContain("Allow: /");
    }
    expect(buildRobotsTxt("https://example.com").split("\n")).toContain("Allow: /");
    expect(buildRobotsTxt("https://localhost.example.com").split("\n")).toContain("Allow: /");
  });
});

describe("llms.txt", () => {
  it("summarises the product, links every key page and lists all published Articles", async () => {
    const outDir = await tempDir();

    await build(outDir);

    const llms = await readFile(path.join(outDir, "llms.txt"), "utf8");
    const lines = llms.split("\n");
    expect(lines[0]).toBe("# AI 视频学习助手");
    expect(llms).toMatch(/^> .+$/m);

    for (const [label, route] of [
      ["首页", "/"],
      ["功能", "/features"],
      ["指南", "/guide"],
      ["FAQ", "/faq"],
      ["文章", "/articles"],
      ["价格", "/pricing"],
      ["条款", "/terms"],
    ]) {
      expect(llms, route).toContain(`[${label}](${route === "/" ? `${ORIGIN}/` : `${ORIGIN}${route}`})`);
    }

    for (const slug of [
      "bilibili-subtitle-download",
      "youtube-study-notes",
      "ai-video-summary-mindmap",
      "douyin-video-parsing",
    ]) {
      expect(llms, slug).toContain(`](${ORIGIN}/articles/${slug})`);
    }
    expect(llms).toContain("B 站视频字幕怎么下载？SRT、VTT 与 TXT 导出步骤");
    expect(llms).toContain("用 YouTube 字幕做学习笔记：导出、整理与复盘");

    // Price and the real usage boundaries are quotable facts, not slogans.
    for (const fact of [
      "3 次",
      "VIP",
      "$4.99/月",
      "2 小时",
      "2 GB",
      "1 小时",
      "15 分钟",
      "不做 ASR",
      "Subtitle",
      "Analysis 私有",
    ]) {
      expect(llms, fact).toContain(fact);
    }

    for (const privatePath of ["/login", "/account", "/analyses", "/verify-email", "/app.html", "/404"]) {
      expect(llms).not.toContain(`${ORIGIN}${privatePath}`);
    }
  });

  it("never lists drafts or private URLs", async () => {
    const outDir = await tempDir();

    await build(outDir, {
      articleSources: [...defaultArticleSources, draftSource()],
      renderRoute: placeholderRoute,
    });

    const llms = await readFile(path.join(outDir, "llms.txt"), "utf8");
    expect(llms).not.toContain("draft-article");
    expect(llms).not.toContain(`${ORIGIN}/login`);
    expect(llms).not.toContain(`${ORIGIN}/app.html`);
  });

  it("names the address a user pastes 页面地址, the README term", async () => {
    const outDir = await tempDir();

    await build(outDir);

    const llms = await readFile(path.join(outDir, "llms.txt"), "utf8");
    expect(llms).toContain("粘贴 B 站或 YouTube 页面地址");
    expect(llms).not.toContain("视频地址");
  });
});

describe("origin handling", () => {
  it("bakes the configured origin into every absolute URL and never leaks localhost", async () => {
    const outDir = await tempDir();
    const origin = "https://learn.example.org";

    await build(outDir, { origin });

    const sitemap = await readFile(path.join(outDir, "sitemap.xml"), "utf8");
    const robots = await readFile(path.join(outDir, "robots.txt"), "utf8");
    const llms = await readFile(path.join(outDir, "llms.txt"), "utf8");
    const home = await readFile(path.join(outDir, "index.html"), "utf8");
    const article = await readFile(
      path.join(outDir, "articles", "bilibili-subtitle-download.html"),
      "utf8",
    );

    for (const artifact of [sitemap, robots, llms]) {
      expect(artifact).toContain(origin);
      expect(artifact).not.toContain("localhost");
      expect(artifact).not.toContain(ORIGIN);
    }
    expect(home).toContain(`<link rel="canonical" href="${origin}/"`);
    expect(article).toContain(`<link rel="canonical" href="${origin}/articles/bilibili-subtitle-download"`);
    for (const page of [home, article]) expect(page).not.toContain(ORIGIN);
    expect(sitemap).toContain(`<loc>${origin}/features</loc>`);
    expect(robots).toContain(`Sitemap: ${origin}/sitemap.xml`);
  });
});
