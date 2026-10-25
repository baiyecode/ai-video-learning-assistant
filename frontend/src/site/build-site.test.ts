/**
 * The single build-product seam: a temp directory receives the real marketing
 * pages, rendered from the real Vue views and the real descriptor registry.
 * Tests parse the written HTML with jsdom; nothing touches the network or Vite.
 */
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

import { JSDOM } from "jsdom";
import { afterEach, describe, expect, it } from "vitest";

import { buildSite } from "@/site/build-site";
import { renderRoute } from "@/site/entry-server";
import { pageDescriptors, type PageDescriptor } from "@/site/seo";

const ORIGIN = "https://example.com";
const SHELL = [
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
].join("\n");

const createdDirs: string[] = [];

async function tempDir(): Promise<string> {
  const dir = await mkdtemp(path.join(tmpdir(), "seo-build-"));
  createdDirs.push(dir);
  return dir;
}

afterEach(async () => {
  await Promise.all(createdDirs.splice(0).map((dir) => rm(dir, { recursive: true, force: true })));
});

function collectTypes(value: unknown, types: string[] = []): string[] {
  if (Array.isArray(value)) {
    for (const item of value) collectTypes(item, types);
  } else if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    if (typeof record["@type"] === "string") types.push(record["@type"]);
    for (const item of Object.values(record)) collectTypes(item, types);
  }
  return types;
}

function findNodeOfType(value: unknown, type: string): Record<string, unknown> | undefined {
  if (Array.isArray(value)) {
    for (const item of value) {
      const found = findNodeOfType(item, type);
      if (found) return found;
    }
  } else if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    if (record["@type"] === type) return record;
    for (const item of Object.values(record)) {
      const found = findNodeOfType(item, type);
      if (found) return found;
    }
  }
  return undefined;
}

function headingLevels(document: Document): number[] {
  return [...document.querySelectorAll("h1, h2, h3, h4, h5, h6")].map((node) =>
    Number(node.tagName.slice(1)),
  );
}

async function readPage(outDir: string, file: string): Promise<Document> {
  const html = await readFile(path.join(outDir, file), "utf8");
  return new JSDOM(html).window.document;
}

async function build(outDir: string, overrides?: Partial<Parameters<typeof buildSite>[0]>): Promise<void> {
  await buildSite({
    origin: ORIGIN,
    descriptors: pageDescriptors,
    shellHtml: SHELL,
    outputDir: outDir,
    renderRoute,
    ...overrides,
  });
}

describe("buildSite", () => {
  it("writes /features as readable static HTML driven by its descriptor", async () => {
    const outDir = await tempDir();

    await build(outDir);

    const html = await readFile(path.join(outDir, "features.html"), "utf8");
    const { document } = new JSDOM(html).window;

    // Vue-rendered body, not a placeholder.
    const headings = [...document.querySelectorAll("h1, h2")].map((node) => node.textContent?.trim());
    expect(headings).toEqual([
      "功能：从解析到 AI 分析",
      "解析",
      "Download：保存文件",
      "Subtitle 导出",
      "Analysis：AI 摘要",
      "思维导图",
      "历史与 VIP",
      "从一次解析开始",
    ]);
    expect(document.querySelectorAll("h1")).toHaveLength(1);
    expect(document.body.textContent).toContain("3 次");
    expect(document.body.textContent).toContain("$4.99/月");
    expect(html).toContain('src="/assets/index-abc123.js"');

    // Exactly one title, description, canonical and robots tag.
    expect(document.querySelectorAll("title")).toHaveLength(1);
    expect(document.title).toBe("功能：视频解析、字幕导出与 AI 分析 · AI 视频学习助手");
    expect(document.querySelectorAll('meta[name="description"]')).toHaveLength(1);
    expect(document.querySelector('meta[name="description"]')?.getAttribute("content")?.length).toBeGreaterThanOrEqual(70);
    expect(document.querySelector("title")?.getAttribute("data-seo-managed")).not.toBeNull();
    expect(document.querySelector('link[rel="canonical"]')?.getAttribute("href")).toBe(
      "https://example.com/features",
    );
    expect(document.querySelector('meta[name="robots"]')?.getAttribute("content")).toBe(
      "index,follow,max-image-preview:large",
    );

    // Open Graph + Twitter Card reuse the same values.
    const og = (property: string) =>
      document.querySelector(`meta[property="${property}"]`)?.getAttribute("content");
    expect(og("og:type")).toBe("website");
    expect(og("og:site_name")).toBe("AI 视频学习助手");
    expect(og("og:title")).toBe(document.title);
    expect(og("og:description")).toBe(
      document.querySelector('meta[name="description"]')?.getAttribute("content"),
    );
    expect(og("og:url")).toBe("https://example.com/features");
    expect(og("og:image")).toBe("https://example.com/brand/share-card.png");
    expect(og("og:image:width")).toBe("1200");
    expect(og("og:image:height")).toBe("630");
    expect(og("og:image:alt")).not.toBe("");
    expect(og("og:locale")).toBe("zh_CN");
    expect(document.querySelector('meta[name="twitter:card"]')?.getAttribute("content")).toBe("summary_large_image");
    expect(document.querySelector('meta[name="twitter:title"]')?.getAttribute("content")).toBe(document.title);
    expect(document.querySelector('meta[name="twitter:image"]')?.getAttribute("content")).toBe(
      "https://example.com/brand/share-card.png",
    );

    // One parseable JSON-LD graph with WebPage + BreadcrumbList.
    const scripts = [...document.querySelectorAll('script[type="application/ld+json"]')];
    expect(scripts).toHaveLength(1);
    const jsonLd = JSON.parse(scripts[0].textContent ?? "");
    const types = collectTypes(jsonLd);
    expect(types).toContain("WebPage");
    expect(types).toContain("BreadcrumbList");
    expect(JSON.stringify(jsonLd)).toContain("https://example.com/features");
  });

  it("writes / as index.html with an origin-root canonical", async () => {
    const outDir = await tempDir();

    await build(outDir);

    const html = await readFile(path.join(outDir, "index.html"), "utf8");
    const featuresHtml = await readFile(path.join(outDir, "features.html"), "utf8");
    const { document } = new JSDOM(html).window;

    expect(document.querySelectorAll("h1")).toHaveLength(1);
    expect(document.title).toBe("视频下载与 AI 分析 · AI 视频学习助手");
    expect(document.title).not.toContain("功能：视频解析");
    expect(document.querySelector('meta[name="description"]')?.getAttribute("content")).not.toBe(
      new JSDOM(featuresHtml).window.document
        .querySelector('meta[name="description"]')
        ?.getAttribute("content"),
    );
    expect(document.querySelector('link[rel="canonical"]')?.getAttribute("href")).toBe(
      "https://example.com/",
    );
    expect(document.querySelector('meta[name="robots"]')?.getAttribute("content")).toBe(
      "index,follow,max-image-preview:large",
    );
    expect(html).toContain("粘贴视频地址");
  });

  it("fails with the offending route when a descriptor is invalid", async () => {
    const outDir = await tempDir();
    const broken = pageDescriptors.map((descriptor) =>
      descriptor.name === "features" ? { ...descriptor, description: "太短" } : descriptor,
    );

    await expect(build(outDir, { descriptors: broken })).rejects.toThrow(/\/features/);
    await expect(build(outDir, { descriptors: broken })).rejects.toThrow(/description/);
  });

  it("fails with the offending route when rendering throws", async () => {
    const outDir = await tempDir();
    const failingRenderer = async (routePath: string) => {
      if (routePath === "/features") throw new Error("view exploded");
      return renderRoute(routePath);
    };

    await expect(build(outDir, { renderRoute: failingRenderer })).rejects.toThrow(
      /\/features.*view exploded/,
    );
  });

  it("rejects two public pages with the same title", async () => {
    const outDir = await tempDir();
    const home = pageDescriptors.find((item) => item.name === "home") as PageDescriptor;
    const duplicated: PageDescriptor[] = pageDescriptors.map((descriptor) =>
      descriptor.name === "features" ? { ...descriptor, title: home.title } : descriptor,
    );

    await expect(build(outDir, { descriptors: duplicated })).rejects.toThrow(/\/features/);
    await expect(build(outDir, { descriptors: duplicated })).rejects.toThrow(/title/);
  });

  it("rejects a descriptor registry that renders two pages to the same file", async () => {
    const outDir = await tempDir();
    const duplicate: PageDescriptor[] = [
      ...pageDescriptors,
      { ...(pageDescriptors.find((item) => item.name === "features") as PageDescriptor) },
    ];

    await expect(build(outDir, { descriptors: duplicate })).rejects.toThrow(/features/);
  });
});

describe("pricing page", () => {
  it("is indexable and its Offer price matches the visible $4.99/月", async () => {
    const outDir = await tempDir();

    await build(outDir);
    const document = await readPage(outDir, "pricing.html");

    // Head: unique title/description, absolute canonical, indexable.
    expect(document.querySelectorAll("h1")).toHaveLength(1);
    expect(document.querySelector("h1")?.textContent?.trim()).toBe("升级 VIP 会员");
    expect(document.title).toBe("价格：免费额度与 VIP 会员 · AI 视频学习助手");
    const description =
      document.querySelector('meta[name="description"]')?.getAttribute("content") ?? "";
    expect(description.length).toBeGreaterThanOrEqual(70);
    expect(description.length).toBeLessThanOrEqual(160);
    expect(document.querySelector('link[rel="canonical"]')?.getAttribute("href")).toBe(
      "https://example.com/pricing",
    );
    expect(document.querySelector('meta[name="robots"]')?.getAttribute("content")).toBe(
      "index,follow,max-image-preview:large",
    );

    // The visible price comes from the billing constant, not a copy-pasted literal.
    const visiblePrice = (document.body.textContent ?? "").match(/\$(\d+\.\d{2})\/月/);
    expect(visiblePrice?.[0]).toBe("$4.99/月");

    // Free vs VIP comparison table with an accessible caption and column headers.
    const table = document.querySelector("table");
    expect(table).not.toBeNull();
    expect(table?.querySelector("caption")?.textContent?.trim()).not.toBe("");
    const columnHeaders = [...(table?.querySelectorAll("thead th") ?? [])];
    expect(columnHeaders.map((node) => node.textContent?.trim())).toEqual([
      "权益",
      "免费账号",
      "VIP 会员",
    ]);
    expect(columnHeaders.every((node) => node.getAttribute("scope") === "col")).toBe(true);
    expect(table?.textContent).toContain("3 次");
    expect(table?.textContent).toContain("Analysis 不限次");

    // Billing and cancellation facts.
    const bodyText = document.body.textContent ?? "";
    expect(bodyText).toContain("Stripe 托管");
    expect(bodyText).toContain("订阅管理");
    expect(bodyText).toContain("当期结束");
    expect(bodyText).toContain("以支付方结账页");

    // Mini FAQ: 4-6 visible questions, each answered.
    const faq = document.querySelector("#pricing-faq");
    expect(faq).not.toBeNull();
    const questions = [...(faq?.querySelectorAll("h3") ?? [])];
    expect(questions.length).toBeGreaterThanOrEqual(4);
    expect(questions.length).toBeLessThanOrEqual(6);
    expect(questions.every((node) => (node.nextElementSibling?.textContent ?? "").trim() !== "")).toBe(
      true,
    );
    expect(faq?.textContent).toContain("取消");
    expect(faq?.textContent).toContain("重置");
    expect(faq?.textContent).toContain("Download");

    // Logged-out SSR renders the login entry with the return path, never the upgrade button.
    const loginEntry = document.querySelector('a[href="/login?next=/pricing"]');
    expect(loginEntry?.textContent?.trim()).toBe("登录后升级");
    expect(bodyText).not.toContain("立即升级");

    // Structured data: WebPage + SoftwareApplication/Offer + BreadcrumbList, no ratings.
    const scripts = [...document.querySelectorAll('script[type="application/ld+json"]')];
    expect(scripts).toHaveLength(1);
    const jsonLd = JSON.parse(scripts[0].textContent ?? "");
    const types = collectTypes(jsonLd);
    expect(types).toEqual(
      expect.arrayContaining(["WebPage", "SoftwareApplication", "Offer", "BreadcrumbList"]),
    );
    expect(types).not.toContain("AggregateRating");
    expect(types).not.toContain("Review");
    expect(JSON.stringify(jsonLd)).toContain("https://example.com/pricing");

    const offer = findNodeOfType(jsonLd, "Offer");
    expect(offer?.price).toBe(4.99);
    expect(offer?.priceCurrency).toBe("USD");
    expect(offer?.availability).toBe("https://schema.org/InStock");
    expect(offer?.url).toBe("https://example.com/pricing");
    // Same constant: JSON-LD price equals the visible headline.
    expect(Number(visiblePrice?.[1])).toBe(offer?.price);
  });
});

describe("terms page", () => {
  it("keeps the clauses and report form under one H1 with WebPage structured data", async () => {
    const outDir = await tempDir();

    await build(outDir);
    const document = await readPage(outDir, "terms.html");

    expect(document.querySelectorAll("h1")).toHaveLength(1);
    expect(document.querySelector("h1")?.textContent?.trim()).toBe("使用条款");
    expect(document.title).toBe("使用条款与举报 · AI 视频学习助手");
    const description =
      document.querySelector('meta[name="description"]')?.getAttribute("content") ?? "";
    expect(description.length).toBeGreaterThanOrEqual(70);
    expect(description.length).toBeLessThanOrEqual(160);
    expect(document.querySelector('link[rel="canonical"]')?.getAttribute("href")).toBe(
      "https://example.com/terms",
    );
    expect(document.querySelector('meta[name="robots"]')?.getAttribute("content")).toBe(
      "index,follow,max-image-preview:large",
    );

    // The existing clauses stay a continuous hierarchy below the only H1.
    expect([...document.querySelectorAll("h2")].map((node) => node.textContent?.trim())).toEqual([
      "一、合规使用",
      "二、禁止用途",
      "三、临时文件与保留策略",
      "四、版权与投诉",
      "五、举报方式",
    ]);
    const levels = headingLevels(document);
    expect(levels[0]).toBe(1);
    for (let index = 1; index < levels.length; index += 1) {
      expect(levels[index] - levels[index - 1]).toBeLessThanOrEqual(1);
    }

    // /terms#report still points at a section that holds the working form.
    const report = document.querySelector("#report");
    expect(report).not.toBeNull();
    expect(report?.querySelector("form")).not.toBeNull();
    expect(report?.querySelectorAll("input, select, textarea").length).toBeGreaterThanOrEqual(4);
    expect(report?.querySelector('button[type="submit"]')?.textContent?.trim()).toBe("提交举报");

    // WebPage + BreadcrumbList only; no article or review markup.
    const scripts = [...document.querySelectorAll('script[type="application/ld+json"]')];
    expect(scripts).toHaveLength(1);
    const jsonLd = JSON.parse(scripts[0].textContent ?? "");
    const types = collectTypes(jsonLd);
    expect(types).toEqual(expect.arrayContaining(["WebPage", "BreadcrumbList"]));
    expect(types).not.toContain("Article");
    expect(types).not.toContain("BlogPosting");
    expect(types).not.toContain("AggregateRating");
    expect(types).not.toContain("Review");
    expect(JSON.stringify(jsonLd)).toContain("https://example.com/terms");
  });
});
