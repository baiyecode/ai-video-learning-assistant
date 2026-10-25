/**
 * Article artifacts through the one build seam: fixture Markdown in, static HTML
 * out. Asserts the list/detail pages, the head contract, JSON-LD dates, the TOC
 * anchors and that dangerous Markdown never reaches the product.
 */
import { readFile, stat } from "node:fs/promises";
import path from "node:path";

import { JSDOM } from "jsdom";
import { describe, expect, it } from "vitest";

import { buildSite } from "@/site/build-site";
import { renderRoute } from "@/site/entry-server";
import type { ArticleSource } from "@/site/articles";
import { pageDescriptors } from "@/site/seo";
import { SHELL, useTempDirs } from "@/site/test-support";

const ORIGIN = "https://example.com";

const BODY_BASE = "这是一段用于构建产物测试的文章正文，包含足够多的字符以便通过长度校验。".repeat(25);

function description(label: string): string {
  return `${label}：这是一段用于构建产物测试的文章描述，需要覆盖七十到一百六十个字符的长度要求，因此这里多写一些具体内容，确保描述足够详细，并说明它适合的使用场景。`;
}

function fixtureSource(
  title: string,
  label: string,
  overrides: { published?: string; updated?: string; tags?: string; draft?: string } = {},
  extraBody = "",
): string {
  const fields = [
    `title: ${title}`,
    `description: ${description(label)}`,
    `published: ${overrides.published ?? "2026-10-25"}`,
    ...(overrides.updated ? [`updated: ${overrides.updated}`] : []),
    ...(overrides.tags ? [`tags: ${overrides.tags}`] : []),
    ...(overrides.draft ? [`draft: ${overrides.draft}`] : []),
  ].join("\n");

  const body = [
    "首段直接回答标题问题：先解析页面地址，再导出 Subtitle。",
    "",
    "## 准备工作",
    "",
    "1. 复制页面地址。",
    "2. 点击解析。",
    "",
    "### 导出细节",
    "",
    "| 格式 | 用途 |",
    "| --- | --- |",
    "| SRT | 剪辑 |",
    "",
    "- 不做 ASR。",
    "- 单视频最长 2 小时、最大 2 GB。",
    "",
    BODY_BASE,
    "",
    "继续阅读 [功能页](/features) 或 [另一篇](/articles/older-post)。",
    extraBody,
  ].join("\n");

  return `---\n${fields}\n---\n\n${body}\n`;
}

const newerSource = fixtureSource(
  "较新的测试文章",
  "较新的测试文章",
  { published: "2026-10-25", updated: "2026-10-30", tags: "[B站, 字幕]" },
  [
    "",
    "<script>alert('xss')</script>",
    "",
    '<iframe src="https://evil.example"></iframe>',
    "",
    '<form action="/steal"><input name="a"></form>',
    "",
    '<img src="/local.png" onerror="alert(1)">',
    "",
    "[危险](javascript:alert(2)) 与 [外部链接](https://example.com/source)",
  ].join("\n"),
);
const olderSource = fixtureSource(
  "较早的测试文章",
  "较早的测试文章",
  { published: "2026-10-01", tags: "[B站]" },
);
const draftSource = fixtureSource(
  "草稿测试文章",
  "草稿测试文章",
  { published: "2026-10-26", draft: "true" },
);

const SOURCES: ArticleSource[] = [
  { fileName: "newer-post.md", source: newerSource },
  { fileName: "older-post.md", source: olderSource },
  { fileName: "draft-post.md", source: draftSource },
];

const tempDir = useTempDirs("article-build-");

async function build(outDir: string, articleSources: readonly ArticleSource[] = SOURCES) {
  return buildSite({
    origin: ORIGIN,
    descriptors: pageDescriptors,
    articleSources,
    shellHtml: SHELL,
    outputDir: outDir,
    renderRoute,
  });
}

function parse(html: string): Document {
  return new JSDOM(html).window.document;
}

function types(value: unknown, found: string[] = []): string[] {
  if (Array.isArray(value)) {
    for (const item of value) types(item, found);
  } else if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    if (typeof record["@type"] === "string") found.push(record["@type"]);
    for (const item of Object.values(record)) types(item, found);
  }
  return found;
}

function jsonLd(document: Document): Record<string, unknown> {
  const script = document.querySelector('script[type="application/ld+json"]');
  return JSON.parse(script?.textContent ?? "{}") as Record<string, unknown>;
}

describe("article artifacts", () => {
  it("lists published Articles newest first with dates, tags and reading time", async () => {
    const outDir = await tempDir();

    await build(outDir);

    const document = parse(await readFile(path.join(outDir, "articles.html"), "utf8"));
    expect(document.querySelectorAll("h1")).toHaveLength(1);
    expect(document.querySelector("h1")?.textContent?.trim()).toBe("文章");
    expect(document.title).toBe("文章 · AI 视频学习助手");
    expect(document.querySelectorAll("title")).toHaveLength(1);
    expect(document.querySelectorAll('meta[name="description"]')).toHaveLength(1);
    expect(document.querySelector('link[rel="canonical"]')?.getAttribute("href")).toBe(
      "https://example.com/articles",
    );
    expect(document.querySelector('meta[name="robots"]')?.getAttribute("content")).toBe(
      "index,follow,max-image-preview:large",
    );

    const headings = [...document.querySelectorAll("h2")].map((node) => node.textContent?.trim());
    expect(headings).toEqual(["较新的测试文章", "较早的测试文章"]);
    expect(document.body.textContent).not.toContain("草稿测试文章");
    expect(document.body.textContent).toContain("2026-10-25");
    expect(document.body.textContent).toContain("B站");
    expect(document.body.textContent).toMatch(/约 \d+ 分钟阅读/);
    expect(document.body.textContent).not.toContain("草稿测试文章");
    expect(document.querySelector('a[href="/articles/newer-post"]')).not.toBeNull();

    const graph = types(jsonLd(document));
    expect(graph).toContain("Blog");
    expect(graph).toContain("BreadcrumbList");
    const blog = JSON.parse(
      document.querySelector('script[type="application/ld+json"]')?.textContent ?? "{}",
    )["@graph"].find((node: { "@type": string }) => node["@type"] === "Blog");
    expect(blog.blogPost).toHaveLength(2);
  });

  it("renders the detail page with one H1, TOC anchors, attribution and related reading", async () => {
    const outDir = await tempDir();

    await build(outDir);

    const html = await readFile(path.join(outDir, "articles/newer-post.html"), "utf8");
    const document = parse(html);

    expect(document.querySelectorAll("h1")).toHaveLength(1);
    expect(document.querySelector("h1")?.textContent?.trim()).toBe("较新的测试文章");
    expect(document.body.textContent).toContain("首段直接回答标题问题");
    expect(document.body.textContent).toContain("AI 视频学习助手团队");
    expect(document.body.textContent).toContain("2026-10-25");
    expect(document.body.textContent).toContain("2026-10-30");
    expect(document.body.textContent).toMatch(/发布于\s*2026-10-25/);
    expect(document.body.textContent).toMatch(/更新于\s*2026-10-30/);
    expect(document.body.textContent).toMatch(/约 \d+ 分钟阅读/);
    expect(document.body.textContent).toContain("不做 ASR");

    // Both dates stay visible even when frontmatter has no separate update date.
    const older = parse(await readFile(path.join(outDir, "articles/older-post.html"), "utf8"));
    expect(older.body.textContent).toMatch(/发布于\s*2026-10-01/);
    expect(older.body.textContent).toMatch(/更新于\s*2026-10-01/);

    const toc = [...document.querySelectorAll('nav[aria-label="文章目录"] a[href^="#"]')];
    expect(toc.length).toBeGreaterThanOrEqual(2);
    for (const link of toc) {
      const id = link.getAttribute("href")?.slice(1) ?? "";
      expect(document.getElementById(id)).not.toBeNull();
    }
    expect(document.getElementById("准备工作")).not.toBeNull();
    expect(document.getElementById("导出细节")).not.toBeNull();

    const relatedLinks = [...document.querySelectorAll('a[href="/articles/older-post"]')].map(
      (link) => link.textContent?.trim(),
    );
    expect(relatedLinks).toContain("较早的测试文章");
    expect(document.querySelector('a[href="/"]')).not.toBeNull();
    expect(document.querySelector('a[href="/features"]')).not.toBeNull();
    expect(document.querySelector('a[href="/articles"]')).not.toBeNull();
  });

  it("writes a unique head, article OG tags and frontmatter-driven BlogPosting", async () => {
    const outDir = await tempDir();

    await build(outDir);

    const document = parse(await readFile(path.join(outDir, "articles/newer-post.html"), "utf8"));
    const og = (property: string) =>
      document.querySelector(`meta[property="${property}"]`)?.getAttribute("content");

    expect(document.querySelectorAll("title")).toHaveLength(1);
    expect(document.title).toBe("较新的测试文章 · AI 视频学习助手");
    expect(document.querySelectorAll('meta[name="description"]')).toHaveLength(1);
    expect(document.querySelector('link[rel="canonical"]')?.getAttribute("href")).toBe(
      "https://example.com/articles/newer-post",
    );
    expect(document.querySelector('meta[name="robots"]')?.getAttribute("content")).toBe(
      "index,follow,max-image-preview:large",
    );
    expect(og("og:type")).toBe("article");
    expect(og("article:published_time")).toBe("2026-10-25");
    expect(og("article:modified_time")).toBe("2026-10-30");
    expect(document.querySelector('meta[name="twitter:card"]')?.getAttribute("content")).toBe(
      "summary_large_image",
    );

    const graph = jsonLd(document)["@graph"] as Array<Record<string, any>>;
    const posting = graph.find((node) => node["@type"] === "BlogPosting");
    if (!posting) throw new Error("BlogPosting missing");
    expect(posting.datePublished).toBe("2026-10-25");
    expect(posting.dateModified).toBe("2026-10-30");
    expect(posting.headline).toBe("较新的测试文章");
    expect(posting.inLanguage).toBe("zh-CN");
    expect(posting.author).toMatchObject({ "@type": "Organization", name: "AI 视频学习助手团队" });
    expect(posting.publisher).toMatchObject({ "@type": "Organization" });
    expect(posting.mainEntityOfPage).toMatchObject({
      "@id": "https://example.com/articles/newer-post",
    });
    expect(posting.image).toEqual(["https://example.com/brand/share-card.png"]);
    expect(graph.find((node) => node["@type"] === "BreadcrumbList")).toBeDefined();
  });

  it("keeps dangerous Markdown out of the artifact and hardens external links", async () => {
    const outDir = await tempDir();

    await build(outDir);

    const html = await readFile(path.join(outDir, "articles/newer-post.html"), "utf8");
    const document = parse(html);

    expect(html).not.toMatch(/alert\('xss'\)/);
    expect(html).not.toMatch(/<iframe/i);
    expect(html).not.toMatch(/<form/i);
    expect(html).not.toMatch(/onerror/i);
    expect(html).not.toMatch(/javascript:/i);
    expect(document.querySelector('a[href="https://example.com/source"]')?.getAttribute("rel")).toBe(
      "noopener noreferrer",
    );
    expect(document.querySelector('a[href="/features"]')?.getAttribute("rel")).toBeNull();
  });

  it("never emits a page for a draft and keeps it out of the list", async () => {
    const outDir = await tempDir();

    const { pages } = await build(outDir);

    expect(pages.map((page) => page.path)).not.toContain("/articles/draft-post");
    await expect(stat(path.join(outDir, "articles", "draft-post.html"))).rejects.toThrow();
  });

  it("publishes the real seed Article with product facts and no over-promising", async () => {
    const outDir = await tempDir();

    await buildSite({
      origin: ORIGIN,
      descriptors: pageDescriptors,
      shellHtml: SHELL,
      outputDir: outDir,
      renderRoute,
    });

    const list = parse(await readFile(path.join(outDir, "articles.html"), "utf8"));
    expect(list.body.textContent).toContain("B 站视频字幕怎么下载？SRT、VTT 与 TXT 导出步骤");

    const html = await readFile(
      path.join(outDir, "articles", "bilibili-subtitle-download.html"),
      "utf8",
    );
    const document = parse(html);
    const text = document.body.textContent ?? "";

    expect(document.querySelectorAll("h1")).toHaveLength(1);
    expect(document.querySelector("h1")?.textContent?.trim()).toContain("B 站视频字幕怎么下载");
    expect(text).toContain("不做 ASR");
    expect(text).toContain("2 小时");
    expect(text).toContain("2 GB");
    expect(text).toContain("15 分钟");
    expect(text).toContain("1 小时");
    expect(text).toContain("3 次");
    expect(text).toContain("$4.99/月");
    expect(document.querySelectorAll('a[href="/"], a[href="/features"], a[href="/pricing"]').length).toBeGreaterThanOrEqual(3);

    for (const promise of ["支持所有平台", "无水印", "自动转写", "永久免费", "100%", "破解"]) {
      expect(text).not.toContain(promise);
    }
    expect(html).not.toMatch(/<iframe/i);
  });

  it("fails the build with the file name when content is invalid", async () => {
    const outDir = await tempDir();
    const broken: ArticleSource[] = [
      {
        fileName: "broken-article.md",
        source: "---\ntitle: 坏文章\ndescription: 太短\npublished: 2026-10-25\n---\n\n正文\n",
      },
    ];

    await expect(build(outDir, broken)).rejects.toThrow(/broken-article\.md/);
  });
});
