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
