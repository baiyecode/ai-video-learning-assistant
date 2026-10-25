/**
 * Private artifacts through the single build seam: the indexable public pages
 * plus a non-indexable SPA shell (``app.html``) and a real 404 document
 * (``404.html``). Parsed with jsdom; no network, no Vite build.
 */
import { readFile } from "node:fs/promises";
import path from "node:path";

import { JSDOM } from "jsdom";
import { describe, expect, it } from "vitest";

import { buildSite } from "@/site/build-site";
import { renderRoute } from "@/site/entry-server";
import { applyHead } from "@/site/head";
import { pageDescriptors, type PageDescriptor } from "@/site/seo";
import { SHELL, useTempDirs } from "@/site/test-support";

const ORIGIN = "https://example.com";
const NOINDEX = "noindex,nofollow";
const tempDir = useTempDirs("seo-private-");

async function build(outDir: string): Promise<void> {
  await buildSite({
    origin: ORIGIN,
    descriptors: pageDescriptors,
    shellHtml: SHELL,
    outputDir: outDir,
    renderRoute,
  });
}

async function readDocument(outDir: string, file: string): Promise<{ html: string; document: Document }> {
  const html = await readFile(path.join(outDir, file), "utf8");
  return { html, document: new JSDOM(html).window.document };
}

describe("app.html (private SPA shell)", () => {
  it("ships the client shell as noindex with hashed assets and no page body", async () => {
    const outDir = await tempDir();
    await build(outDir);

    const { html, document } = await readDocument(outDir, "app.html");

    // Exactly one plain title and one robots directive; no canonical/OG/marketing head.
    expect(document.querySelectorAll("title")).toHaveLength(1);
    expect(document.title).toBe("AI 视频学习助手");
    expect(document.querySelectorAll('meta[name="robots"]')).toHaveLength(1);
    expect(document.querySelector('meta[name="robots"]')?.getAttribute("content")).toBe(NOINDEX);
    expect(document.querySelector('link[rel="canonical"]')).toBeNull();
    expect(document.querySelector('meta[name="description"]')).toBeNull();
    expect(document.querySelector('meta[property^="og:"]')).toBeNull();
    expect(document.querySelector('script[type="application/ld+json"]')).toBeNull();

    // The hashed client build tags survive, so the SPA boots for private routes.
    expect(html).toContain('src="/assets/index-abc123.js"');
    expect(html).toContain('href="/assets/index-abc123.css"');

    // The mount is empty: no marketing or Article body is baked into the shell.
    expect(document.querySelector("#app")?.textContent?.trim()).toBe("");
    expect(document.querySelector("#app")?.children).toHaveLength(0);
    expect(html).not.toContain("粘贴视频地址");
    expect(html).not.toContain("B 站字幕");
    expect(document.querySelectorAll("h1")).toHaveLength(0);
  });

  it("is not advertised in sitemap.xml or llms.txt", async () => {
    const outDir = await tempDir();
    await build(outDir);

    const sitemap = await readFile(path.join(outDir, "sitemap.xml"), "utf8");
    const llms = await readFile(path.join(outDir, "llms.txt"), "utf8");

    expect(sitemap).not.toContain("app.html");
    expect(llms).not.toContain("app.html");
    expect(await readFile(path.join(outDir, "robots.txt"), "utf8")).toContain("Disallow: /app.html");
  });

  it("keeps a single noindex head when the client router takes over", async () => {
    const outDir = await tempDir();
    await build(outDir);
    const { document } = await readDocument(outDir, "app.html");
    const login = pageDescriptors.find((descriptor) => descriptor.name === "login");
    expect(login).toBeDefined();

    applyHead(login as PageDescriptor, ORIGIN, document);

    expect(document.querySelectorAll("title")).toHaveLength(1);
    expect(document.title).toBe("登录 · AI 视频学习助手");
    expect(document.querySelectorAll('meta[name="robots"]')).toHaveLength(1);
    expect(document.querySelector('meta[name="robots"]')?.getAttribute("content")).toBe(NOINDEX);
  });
});

describe("404.html", () => {
  it("renders the NotFoundView once with a noindex head and the client shell tags", async () => {
    const outDir = await tempDir();
    await build(outDir);

    const { html, document } = await readDocument(outDir, "404.html");

    expect(document.querySelectorAll("h1")).toHaveLength(1);
    expect(document.querySelector("h1")?.textContent?.trim()).toBe("页面不存在");
    expect(document.querySelectorAll("title")).toHaveLength(1);
    expect(document.title).toBe("页面不存在 · AI 视频学习助手");
    expect(document.querySelectorAll('meta[name="robots"]')).toHaveLength(1);
    expect(document.querySelector('meta[name="robots"]')?.getAttribute("content")).toBe(NOINDEX);
    expect(document.querySelector('link[rel="canonical"]')).toBeNull();
    expect(document.querySelector('meta[property^="og:"]')).toBeNull();

    expect(html).toContain('src="/assets/index-abc123.js"');
    expect(html).toContain('href="/assets/index-abc123.css"');
    const homeLinks = [...document.querySelectorAll('#app a[href="/"]')].map((node) =>
      node.textContent?.trim(),
    );
    expect(homeLinks).toContain("返回首页");

    // Never the home page: no marketing body, no placeholder title, no indexable meta.
    expect(html).not.toContain("粘贴视频地址");
    expect(html).not.toContain("stale shell description");
    expect(html).not.toContain('content="index,follow');
  });

  it("is not listed in the sitemap or llms.txt", async () => {
    const outDir = await tempDir();
    await build(outDir);

    const sitemap = await readFile(path.join(outDir, "sitemap.xml"), "utf8");
    const llms = await readFile(path.join(outDir, "llms.txt"), "utf8");

    expect(sitemap).not.toContain("404.html");
    expect(llms).not.toContain("404.html");
  });
});
