/**
 * The four seed Articles as a content set: exactly these slugs, newest first,
 * every one meeting the editorial minimums (800 CJK characters, three internal
 * links, a list or table, an answering first paragraph) and the real detail
 * pages carrying the facts the copy must not get wrong.
 */
import { mkdtemp, readFile, rm, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

import { JSDOM } from "jsdom";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

import { extractInternalLinks, parseArticle } from "@/site/articles";
import { defaultArticleCollection, defaultArticleSources } from "@/site/article-sources";
import { buildSite } from "@/site/build-site";
import { renderRoute } from "@/site/entry-server";
import { pageDescriptors } from "@/site/seo";

const ORIGIN = "https://example.com";

/** The published set, newest first. Dates are part of the contract. */
const SEED_ARTICLES = [
  { slug: "bilibili-subtitle-download", published: "2026-10-25" },
  { slug: "youtube-study-notes", published: "2026-10-24" },
  { slug: "ai-video-summary-mindmap", published: "2026-10-23" },
  { slug: "douyin-video-parsing", published: "2026-10-22" },
] as const;

/** Promises the product cannot keep. */
const FORBIDDEN_PHRASES = [
  "支持所有平台",
  "无水印",
  "自动转写",
  "永久免费",
  "DRM 破解",
  "100% 成功",
] as const;

/** Each opener must answer its title instead of warming up. */
const FIRST_PARAGRAPH_ANSWERS: Record<string, string[]> = {
  "bilibili-subtitle-download": ["粘贴", "导出"],
  "youtube-study-notes": ["导出", "笔记"],
  "ai-video-summary-mindmap": ["Subtitle", "摘要"],
  "douyin-video-parsing": ["灰度", "422"],
};

function countCjk(text: string): number {
  return (text.match(/[\u4e00-\u9fff]/gu) ?? []).length;
}

function firstParagraph(body: string): string {
  return body.split("\n").find((line) => line.trim() !== "")?.trim() ?? "";
}

function hasListOrTable(body: string): boolean {
  return (
    /^\s*[-*+]\s+\S/m.test(body) ||
    /^\s*\d+\.\s+\S/m.test(body) ||
    /^\|.+\|\s*$/m.test(body)
  );
}

function parse(html: string): Document {
  return new JSDOM(html).window.document;
}

const collection = defaultArticleCollection();
const createdDirs: string[] = [];
let outDir = "";

beforeAll(async () => {
  outDir = await mkdtemp(path.join(tmpdir(), "seed-articles-"));
  createdDirs.push(outDir);
  await buildSite({
    origin: ORIGIN,
    descriptors: pageDescriptors,
    shellHtml: [
      "<!doctype html>",
      '<html lang="zh-CN">',
      "  <head>",
      '    <meta charset="UTF-8" />',
      '    <meta name="description" content="stale shell description" />',
      "    <title>AI 视频学习助手</title>",
      "  </head>",
      '  <body class="bg-slate-50">',
      '    <div id="app"></div>',
      '    <script type="module" src="/assets/index-abc123.js"></script>',
      "  </body>",
      "</html>",
    ].join("\n"),
    outputDir: outDir,
    renderRoute,
  });
}, 60_000);

afterAll(async () => {
  await Promise.all(createdDirs.splice(0).map((dir) => rm(dir, { recursive: true, force: true })));
});

describe("seed Article collection", () => {
  it("publishes exactly the four seed Articles, newest first, with real dates", () => {
    expect(collection.published.map(({ slug, published }) => ({ slug, published }))).toEqual(
      SEED_ARTICLES.map(({ slug, published }) => ({ slug, published })),
    );
    expect(collection.drafts).toHaveLength(0);
    expect(new Set(collection.published.map((article) => article.published)).size).toBe(4);

    for (const article of collection.published) {
      if (article.updated) expect(article.updated >= article.published).toBe(true);
    }
  });

  it("meets the length, linking and structure minimums", () => {
    for (const article of collection.published) {
      expect(countCjk(article.body), `${article.fileName} CJK characters`).toBeGreaterThanOrEqual(800);
      expect(
        extractInternalLinks(article.body).length,
        `${article.fileName} internal links`,
      ).toBeGreaterThanOrEqual(3);
      expect(hasListOrTable(article.body), `${article.fileName} list or table`).toBe(true);
    }
  });

  it("opens with a paragraph that answers the title question", () => {
    for (const article of collection.published) {
      const opener = firstParagraph(article.body);
      expect(opener.startsWith("#"), `${article.fileName} first block`).toBe(false);
      expect(opener.length, `${article.fileName} opener length`).toBeGreaterThanOrEqual(60);
      for (const answer of FIRST_PARAGRAPH_ANSWERS[article.slug] ?? []) {
        expect(opener, `${article.fileName} opener mentions ${answer}`).toContain(answer);
      }
    }
  });

  it("never promises what the product cannot deliver", () => {
    for (const article of collection.published) {
      const source = `${article.title}\n${article.description}\n${article.body}`;
      for (const phrase of FORBIDDEN_PHRASES) {
        expect(source, `${article.fileName} contains ${phrase}`).not.toContain(phrase);
      }
    }
  });
});

/**
 * The literal-claim guard (ticket #48) asserted on the real content sources:
 * every money or quota claim in the four seed Markdown files goes through a
 * placeholder, so the strict build-time guard passes out of the box — and the
 * legitimate ``1 次 Quota`` / ``消耗 1 次`` lines (a consumption unit, not a
 * daily quota claim) prove the guard does not over-flag bare counts.
 */
describe("seed Article sources pass the literal-claim guard", () => {
  it("each of the four real sources parses under the guard", () => {
    expect(defaultArticleSources).toHaveLength(4);
    for (const { fileName, source } of defaultArticleSources) {
      expect(fileName).toMatch(/\.md$/);
      expect(() => parseArticle(fileName, source), `${fileName} trips the guard`).not.toThrow();
    }
  });

  it("the real sources carry templated claims, not hand-written ones", () => {
    for (const { fileName, source } of defaultArticleSources) {
      expect(source, `${fileName} uses at least one placeholder`).toMatch(
        /\{\{(?:MONTHLY_PRICE_USD|DAILY_FREE_QUOTA)\}\}/,
      );
      expect(source, `${fileName} has no literal monthly price`).not.toMatch(/\$[\d.]+\/月/);
      expect(source, `${fileName} has no literal daily quota`).not.toMatch(
        /(?:每日|每天|自然日)\s*\d+\s*次/,
      );
    }
  });

  it("the mindmap source keeps its legal single-consumption counts", () => {
    const mindmap = defaultArticleSources.find(
      ({ fileName }) => fileName === "ai-video-summary-mindmap.md",
    );
    expect(mindmap?.source).toContain("1 次 Quota");
    expect(mindmap?.source).toContain("消耗 1 次");
    expect(() => parseArticle(mindmap!.fileName, mindmap!.source)).not.toThrow();
  });
});

describe("seed Article artifacts", () => {
  it("lists all four Articles newest first", async () => {
    const document = parse(await readFile(path.join(outDir, "articles.html"), "utf8"));

    expect(document.querySelectorAll("h1")).toHaveLength(1);
    expect(
      [...document.querySelectorAll("h2")].map((node) => node.textContent?.trim()),
    ).toEqual([
      ...collection.published.map((article) => article.title),
      // Back-to-tool CTA closes the index page (P3 story 12).
      "读完就试一次",
    ]);
    expect(document.querySelectorAll('a[href^="/articles/"]')).toHaveLength(4);
  });

  it("renders a complete detail page for every seed Article", async () => {
    for (const article of collection.published) {
      const file = path.join(outDir, "articles", `${article.slug}.html`);
      await expect(stat(file), `${article.slug}.html exists`).resolves.toBeTruthy();
      const html = await readFile(file, "utf8");
      const document = parse(html);
      const text = document.body.textContent ?? "";

      expect(document.querySelectorAll("h1"), `${article.slug} H1 count`).toHaveLength(1);
      expect(document.querySelector("h1")?.textContent?.trim()).toBe(article.title);
      expect(text).toContain("AI 视频学习助手团队");
      expect(text).toContain(article.published);
      expect(text).toMatch(/约 \d+ 分钟阅读/);

      const toc = [...document.querySelectorAll('nav[aria-label="文章目录"] a[href^="#"]')];
      expect(toc.length, `${article.slug} TOC entries`).toBeGreaterThanOrEqual(2);
      for (const link of toc) {
        const id = link.getAttribute("href")?.slice(1) ?? "";
        expect(document.getElementById(id), `${article.slug} anchor ${id}`).not.toBeNull();
      }

      for (const phrase of FORBIDDEN_PHRASES) {
        expect(text, `${article.slug} page contains ${phrase}`).not.toContain(phrase);
      }
    }
  });

  it("states the Douyin rollout, watermark and 422 semantics", async () => {
    const text = await pageText("douyin-video-parsing");

    expect(text).toContain("APP_DOUYIN_ENABLED");
    expect(text).toContain("默认关闭");
    expect(text).toContain("422");
    expect(text).toContain("抖音暂未开放");
    expect(text).toContain("带水印");
    expect(text).toContain("Subtitle");
    expect(text).not.toContain("全量支持");
  });

  it("states the Analysis quota, VIP price and no-subtitle rule", async () => {
    const text = await pageText("ai-video-summary-mindmap");

    expect(text).toContain("3 次");
    expect(text).toContain("$4.99/月");
    expect(text).toContain("Asia/Shanghai");
    expect(text).toContain("Subtitle");
    expect(text).toContain("不做 ASR");
    expect(text).toContain("失败");
    expect(text).toContain("仅本人");
    expect(text).toContain("2 小时");
    expect(text).toContain("2 GB");
    expect(text).toContain("下载");
  });

  it("states YouTube manual vs auto subtitles and the no-ASR boundary", async () => {
    const text = await pageText("youtube-study-notes");

    expect(text).toContain("人工");
    expect(text).toContain("自动生成");
    expect(text).toContain("不做 ASR");
    expect(text).toContain("SRT");
    expect(text).toContain("VTT");
    expect(text).toContain("TXT");
  });

  it("states the concrete limits every Article shares", async () => {
    for (const slug of SEED_ARTICLES.map((article) => article.slug)) {
      const text = await pageText(slug);
      for (const fact of ["2 小时", "2 GB", "15 分钟", "1 小时", "3 次", "$4.99/月"]) {
        expect(text, `${slug} states ${fact}`).toContain(fact);
      }
    }
  });
});

async function pageText(slug: string): Promise<string> {
  const html = await readFile(path.join(outDir, "articles", `${slug}.html`), "utf8");
  return parse(html).body.textContent ?? "";
}
