/**
 * Brand assets and the social-share contract, asserted on the real build
 * artifact: the actual shell, the actual descriptor registry and the local
 * files under ``public/``. No network, no external image hosts.
 *
 * The share-image loop iterates the public descriptor registry, so article
 * pages registered later are covered without editing this test.
 */
import { readFileSync, existsSync } from "node:fs";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { JSDOM } from "jsdom";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

import { buildSite } from "@/site/build-site";
import { renderRoute } from "@/site/entry-server";
import {
  DEFAULT_SHARE_IMAGE,
  INDEX_ROBOTS,
  SITE_NAME,
  headTags,
  pageDescriptors,
  publicDescriptors,
  type PageDescriptor,
} from "@/site/seo";

const ORIGIN = "https://example.com";
const FRONTEND_ROOT = path.resolve(fileURLToPath(new URL("../..", import.meta.url)));
const PUBLIC_DIR = path.join(FRONTEND_ROOT, "public");

let outDir = "";
let shellHtml = "";
let builtFiles: string[] = [];

beforeAll(async () => {
  outDir = await mkdtemp(path.join(tmpdir(), "brand-build-"));
  shellHtml = await readFile(path.join(FRONTEND_ROOT, "index.html"), "utf8");
  const { pages } = await buildSite({
    origin: ORIGIN,
    descriptors: pageDescriptors,
    shellHtml,
    outputDir: outDir,
    renderRoute,
  });
  builtFiles = pages.map((page) => page.file);
});

afterAll(async () => {
  if (outDir) await rm(outDir, { recursive: true, force: true });
});

/** Read width/height from the PNG IHDR chunk without a decoder dependency. */
function pngSize(file: string): { width: number; height: number } {
  const buffer = readFileSync(file);
  const signature = buffer.subarray(0, 8).toString("hex");
  if (signature !== "89504e470d0a1a0a") {
    throw new Error(`${file} is not a PNG`);
  }
  return { width: buffer.readUInt32BE(16), height: buffer.readUInt32BE(20) };
}

function metaContent(document: Document, selector: string): string | null {
  return document.querySelector(selector)?.getAttribute("content") ?? null;
}

async function documentFor(file: string): Promise<Document> {
  return new JSDOM(await readFile(path.join(outDir, file), "utf8")).window.document;
}

function localAssetFor(url: string): string {
  return path.join(PUBLIC_DIR, new URL(url).pathname);
}

describe("brand assets", () => {
  it("ships a vector favicon and the declared 512px / 1200x630 raster assets", () => {
    const favicon = path.join(PUBLIC_DIR, "favicon.svg");
    const icon = path.join(PUBLIC_DIR, "brand", "icon-512.png");
    const shareCard = path.join(PUBLIC_DIR, "brand", "share-card.png");

    expect(existsSync(favicon)).toBe(true);
    const svg = readFileSync(favicon, "utf8");
    expect(svg).toMatch(/^<svg[\s>]/);
    expect(svg).toContain("viewBox");

    expect(pngSize(icon)).toEqual({ width: 512, height: 512 });
    expect(pngSize(shareCard)).toEqual({ width: 1200, height: 630 });
  });

  it("links the favicon and the brand icon from every produced HTML shell", async () => {
    expect(shellHtml).toContain('rel="icon"');
    expect(shellHtml).toContain("/favicon.svg");
    expect(shellHtml).toContain('rel="apple-touch-icon"');
    expect(shellHtml).toContain("/brand/icon-512.png");

    for (const file of builtFiles) {
      const document = await documentFor(file);
      expect(document.querySelector('link[rel="icon"][type="image/svg+xml"]')?.getAttribute("href")).toBe(
        "/favicon.svg",
      );
      expect(document.querySelector('link[rel="apple-touch-icon"]')?.getAttribute("href")).toBe(
        "/brand/icon-512.png",
      );
    }
  });
});

describe("social share contract", () => {
  it("gives every public page an absolute 1200x630 share image with alt text", async () => {
    const publicPages = publicDescriptors(pageDescriptors);
    expect(publicPages.length).toBeGreaterThan(0);
    expect(builtFiles).toHaveLength(publicPages.length);

    for (const file of builtFiles) {
      const document = await documentFor(file);
      const ogImage = metaContent(document, 'meta[property="og:image"]');
      const twitterImage = metaContent(document, 'meta[name="twitter:image"]');

      expect(ogImage, `${file} og:image`).toMatch(/^https:\/\/example\.com\//);
      expect(twitterImage, `${file} twitter:image`).toBe(ogImage);
      expect(metaContent(document, 'meta[property="og:image:width"]')).toBe("1200");
      expect(metaContent(document, 'meta[property="og:image:height"]')).toBe("630");
      expect(metaContent(document, 'meta[property="og:image:alt"]')?.trim()).toBeTruthy();

      const asset = localAssetFor(ogImage as string);
      expect(existsSync(asset), `${file} -> ${asset}`).toBe(true);
      expect(pngSize(asset)).toEqual({ width: 1200, height: 630 });
    }
  });

  it("publishes an Organization node with the absolute 512px logo on every public page", async () => {
    for (const file of builtFiles) {
      const document = await documentFor(file);
      const scripts = [...document.querySelectorAll('script[type="application/ld+json"]')];
      expect(scripts, `${file} JSON-LD`).toHaveLength(1);

      const graph = JSON.parse(scripts[0].textContent ?? "") as {
        "@graph"?: Array<Record<string, unknown>>;
      };
      const nodes = graph["@graph"] ?? [];
      const organization = nodes.find((node) => node["@type"] === "Organization") as
        | { "@id"?: string; name?: string; url?: string; logo?: { url?: string } }
        | undefined;

      expect(organization, `${file} Organization`).toBeDefined();
      expect(organization?.name).toBe(SITE_NAME);
      expect(organization?.url).toBe("https://example.com/");
      expect(organization?.logo?.url).toBe("https://example.com/brand/icon-512.png");
      expect(organization?.["@id"]).toBe("https://example.com/#organization");
    }
  });

  it("adds the Organization as publisher to article descriptors", () => {
    const article: PageDescriptor = {
      name: "article-fixture",
      path: "/articles/fixture",
      title: "测试文章",
      description:
        "这篇文章用于验证文章类描述符会自动获得组织发布者引用，并复用全站分享图与绝对地址；正文与标题只服务于构建产物测试，不包含任何真实内容、外部依赖或用户数据。",
      robots: INDEX_ROBOTS,
      ogType: "article",
      image: DEFAULT_SHARE_IMAGE,
      jsonLd: (context) => [
        {
          "@type": "BlogPosting",
          "@id": `${context.canonicalUrl}#article`,
          headline: "测试文章",
          mainEntityOfPage: context.canonicalUrl,
        },
      ],
    };

    const script = headTags(article, ORIGIN).find((tag) => tag.tag === "script");
    const graph = JSON.parse(script?.text ?? "") as {
      "@graph"?: Array<Record<string, unknown>>;
    };
    const nodes = graph["@graph"] ?? [];
    const organization = nodes.find((node) => node["@type"] === "Organization") as
      | { "@id"?: string }
      | undefined;
    const posting = nodes.find((node) => node["@type"] === "BlogPosting") as
      | { publisher?: { "@id"?: string } }
      | undefined;

    expect(organization?.["@id"]).toBe("https://example.com/#organization");
    expect(posting?.publisher?.["@id"]).toBe(organization?.["@id"]);
  });
});
