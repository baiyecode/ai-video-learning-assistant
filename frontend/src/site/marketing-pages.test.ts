/**
 * Artifact seam for the P3-04 marketing surface: build once into a temp
 * directory, then assert the real HTML for `/`, `/guide` and `/faq` plus the
 * navigation and cross-page consistency rules. No network, no Vite.
 */
import { readFile } from "node:fs/promises";
import path from "node:path";

import { JSDOM } from "jsdom";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

import { defaultArticleCollection } from "@/site/article-sources";
import { buildSite, type BuildSiteResult } from "@/site/build-site";
import { renderRoute } from "@/site/entry-server";
import { pageDescriptors } from "@/site/seo";
import { createTempDir, removeTempDirs, SHELL } from "@/site/test-support";

const ORIGIN = "https://example.com";

let outDir = "";
let build: BuildSiteResult;
const documents = new Map<string, Document>();

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

function jsonLd(document: Document): Record<string, unknown> {
  const scripts = [...document.querySelectorAll('script[type="application/ld+json"]')];
  expect(scripts).toHaveLength(1);
  return JSON.parse(scripts[0].textContent ?? "") as Record<string, unknown>;
}

function bodyText(document: Document): string {
  return (document.body.textContent ?? "").replace(/\s+/g, " ").trim();
}

function headingLevels(document: Document): number[] {
  return [...document.querySelectorAll("main h1, main h2, main h3, main h4, main h5, main h6")].map(
    (node) => Number(node.tagName.slice(1)),
  );
}

function textOf(node: Element | null): string {
  return (node?.textContent ?? "").replace(/\s+/g, " ").trim();
}

beforeAll(async () => {
  outDir = await createTempDir("seo-marketing-");
  build = await buildSite({
    origin: ORIGIN,
    descriptors: pageDescriptors,
    shellHtml: SHELL,
    outputDir: outDir,
    renderRoute,
  });
  for (const file of ["index.html", "guide.html", "faq.html", "features.html", "articles.html"]) {
    const html = await readFile(path.join(outDir, file), "utf8");
    const dom = new JSDOM(html);
    documents.set(file, dom.window.document);
  }
});

afterAll(async () => {
  if (outDir) await removeTempDirs([outDir]);
});

function page(file: string): Document {
  const document = documents.get(file);
  if (!document) throw new Error(`page ${file} was not built`);
  return document;
}

describe("home marketing page", () => {
  it("keeps one H1 and renders the tool plus the marketing sections", () => {
    const document = page("index.html");

    expect(document.querySelectorAll("h1")).toHaveLength(1);
    expect(textOf(document.querySelector("h1"))).toContain("粘贴视频地址");
    expect(document.querySelector("title")?.textContent).toBe(
      "视频下载、字幕导出与 AI 摘要 · AI 视频学习助手",
    );
    expect(document.querySelector('link[rel="canonical"]')?.getAttribute("href")).toBe(
      "https://example.com/",
    );
    expect(document.querySelector('meta[name="robots"]')?.getAttribute("content")).toBe(
      "index,follow,max-image-preview:large",
    );
    const description = document
      .querySelector('meta[name="description"]')
      ?.getAttribute("content") ?? "";
    expect(description.length).toBeGreaterThanOrEqual(70);
    expect(description.length).toBeLessThanOrEqual(160);
    for (const keyword of ["视频下载", "字幕", "AI 摘要"]) {
      expect(description).toContain(keyword);
    }

    // The tool keeps its input and the compliance line the golden path asserts.
    expect(document.querySelector('input[aria-label="视频地址"]')).not.toBeNull();
    expect(
      page("index.html").body.textContent,
    ).toContain("仅限个人备份或已获授权内容，不支持播放列表、直播与 DRM 内容。");

    // No JavaScript: the tool is unavailable, the marketing content stays.
    const noscript = document.querySelector("noscript");
    expect(textOf(noscript)).toContain("JavaScript");

    for (const heading of [
      "三步完成一次解析",
      "六项能力",
      "支持的 Platform 与限制",
      "价格与升级",
      "最新文章",
      "合规使用",
    ]) {
      const match = [...document.querySelectorAll("h2")].some(
        (node) => textOf(node) === heading,
      );
      expect(match, `missing H2 ${heading}`).toBe(true);
    }
    expect(textOf(document.querySelector("#home-compliance"))).toContain("个人备份");

    // The value-prop link returns to the tool form, not to an arbitrary anchor.
    const backToTool = [...document.querySelectorAll("#home-value a")].find((node) =>
      textOf(node).includes("回到解析表单"),
    );
    expect(backToTool).toBeDefined();
    expect(backToTool?.getAttribute("href")).toBe("#resolve");
    expect(document.getElementById("resolve")).not.toBeNull();
  });

  it("lists the three steps and six capabilities in reading order", () => {
    const document = page("index.html");

    expect([...document.querySelectorAll("#home-steps li h3")].map(textOf)).toEqual([
      "解析",
      "下载或导出 Subtitle",
      "登录生成 Analysis",
    ]);
    expect([...document.querySelectorAll("#home-capabilities h3")].map(textOf)).toEqual([
      "解析",
      "Download",
      "Subtitle 导出",
      "Analysis",
      "思维导图",
      "历史与 VIP",
    ]);
    const capabilityLinks = [
      ...document.querySelectorAll('#home-capabilities a[href="/features"]'),
    ];
    expect(capabilityLinks).toHaveLength(6);
    expect(textOf(document.querySelector("#home-pricing"))).toContain("$4.99/月");
    expect(document.querySelector('#home-pricing a[href="/pricing"]')).not.toBeNull();
  });

  it("renders the same six capability titles on home and /features", () => {
    const homeTitles = [...page("index.html").querySelectorAll("#home-capabilities h3")].map(textOf);
    const featureTitles = [...page("features.html").querySelectorAll("section > h2")]
      .map(textOf)
      .filter((title) => title !== "从一次解析开始");

    expect(featureTitles).toEqual(homeTitles);
  });

  it("uses the shared guide steps for both the home steps and /guide", () => {
    const homeSteps = [...page("index.html").querySelectorAll("#home-steps li h3")].map(textOf);
    const guideSteps = [...page("guide.html").querySelectorAll("#guide-steps li h3")].map(textOf);

    expect(homeSteps).toEqual(guideSteps);
  });

  it("summarises five FAQ entries drawn from the full FAQ", () => {
    const home = page("index.html");
    const full = page("faq.html");
    const questions = [...home.querySelectorAll("#home-faq h3")];
    const answers = [...home.querySelectorAll("#home-faq p")];

    expect(questions).toHaveLength(5);
    expect(answers).toHaveLength(5);
    const fullText = bodyText(full);
    for (const node of [...questions, ...answers]) {
      expect(fullText, `home FAQ copy missing from /faq: ${textOf(node)}`).toContain(textOf(node));
    }
    expect(home.querySelector('#home-faq a[href="/faq"]')).not.toBeNull();
  });

  it("shows exactly the newest three published Articles in order", () => {
    const document = page("index.html");
    const expected = defaultArticleCollection()
      .published.slice(0, 3)
      .map((article) => `/articles/${article.slug}`);
    const links = [...document.querySelectorAll('#home-articles a[href^="/articles/"]')].map(
      (node) => node.getAttribute("href"),
    );

    expect(links).toEqual(expected);
    for (const article of defaultArticleCollection().published.slice(0, 3)) {
      expect(bodyText(document)).toContain(article.title);
    }
  });

  it("declares WebSite and SoftwareApplication structured data", () => {
    const document = page("index.html");
    const types = collectTypes(jsonLd(document));

    expect(types).toEqual(expect.arrayContaining(["WebSite", "SoftwareApplication", "Offer"]));
    const website = findNodeOfType(jsonLd(document), "WebSite");
    expect(website?.url).toBe("https://example.com/");
    const application = findNodeOfType(jsonLd(document), "SoftwareApplication");
    expect(application?.applicationCategory).toBe("MultimediaApplication");
    expect(application?.operatingSystem).toBe("Web");
  });
});

describe("/guide", () => {
  it("renders one H1, HowTo steps that match the visible steps verbatim", () => {
    const document = page("guide.html");

    expect(document.querySelectorAll("h1")).toHaveLength(1);
    expect(document.querySelector("title")?.textContent).toBe(
      "使用指南：解析、下载与 AI 分析 · AI 视频学习助手",
    );
    expect(document.querySelector('link[rel="canonical"]')?.getAttribute("href")).toBe(
      "https://example.com/guide",
    );
    expect(document.querySelector('meta[name="robots"]')?.getAttribute("content")).toBe(
      "index,follow,max-image-preview:large",
    );
    const description = document
      .querySelector('meta[name="description"]')
      ?.getAttribute("content") ?? "";
    expect(description.length).toBeGreaterThanOrEqual(70);
    expect(description.length).toBeLessThanOrEqual(160);

    const howTo = findNodeOfType(jsonLd(document), "HowTo");
    expect(howTo).toBeDefined();
    const steps = (howTo?.step ?? []) as Record<string, unknown>[];
    expect(steps).toHaveLength(3);
    const visible = bodyText(document);
    for (const step of steps) {
      expect(step["@type"]).toBe("HowToStep");
      expect(visible, `HowTo step name missing: ${String(step.name)}`).toContain(String(step.name));
      expect(visible, `HowTo step text missing: ${String(step.text)}`).toContain(String(step.text));
    }
    expect([...document.querySelectorAll("#guide-steps li h3")].map(textOf)).toEqual(
      steps.map((step) => step.name),
    );
  });

  it("covers platform differences, refusals and troubleshooting", () => {
    const document = page("guide.html");
    const text = bodyText(document);

    for (const platform of ["B 站", "YouTube", "抖音"]) {
      expect(text).toContain(platform);
    }
    for (const topic of [
      "Subtitle",
      "DRM",
      "会员专属",
      "15 分钟",
      "1 小时",
      "Quota",
      "验证邮箱",
      "2 小时",
      "2 GB",
    ]) {
      expect(text, `guide is missing ${topic}`).toContain(topic);
    }
    expect(textOf(document.querySelector('#guide-cta a[href="/"]'))).toContain("回到首页");
    expect(document.querySelector('#guide-more a[href="/faq"]')).not.toBeNull();
  });
});

describe("/faq", () => {
  it("renders one H1 and a FAQPage whose Q/A match the visible text", () => {
    const document = page("faq.html");

    expect(document.querySelectorAll("h1")).toHaveLength(1);
    expect(document.querySelector("title")?.textContent).toBe(
      "常见问题：平台、Quota 与价格 · AI 视频学习助手",
    );
    expect(document.querySelector('link[rel="canonical"]')?.getAttribute("href")).toBe(
      "https://example.com/faq",
    );
    expect(document.querySelector('meta[name="robots"]')?.getAttribute("content")).toBe(
      "index,follow,max-image-preview:large",
    );
    const description = document
      .querySelector('meta[name="description"]')
      ?.getAttribute("content") ?? "";
    expect(description.length).toBeGreaterThanOrEqual(70);
    expect(description.length).toBeLessThanOrEqual(160);

    const faqPage = findNodeOfType(jsonLd(document), "FAQPage");
    const questions = (faqPage?.mainEntity ?? []) as Record<string, unknown>[];
    expect(questions.length).toBeGreaterThanOrEqual(12);
    const visible = bodyText(document);
    for (const question of questions) {
      expect(question["@type"]).toBe("Question");
      expect(visible, `FAQ question missing: ${String(question.name)}`).toContain(
        String(question.name),
      );
      const answer = question.acceptedAnswer as Record<string, unknown>;
      expect(answer["@type"]).toBe("Answer");
      expect(visible, `FAQ answer missing: ${String(answer.text)}`).toContain(String(answer.text));
    }
    expect([...document.querySelectorAll("main h2")].map(textOf)).toEqual(
      expect.arrayContaining(questions.map((question) => question.name)),
    );
  });

  it("answers the required product facts", () => {
    const text = bodyText(page("faq.html"));

    for (const topic of [
      "B 站",
      "YouTube",
      "抖音",
      "灰度",
      "3 次",
      "Asia/Shanghai",
      "$4.99/月",
      "取消",
      "Subtitle",
      "ASR",
      "1 小时",
      "15 分钟",
      "2 小时",
      "2 GB",
      "私有",
      "举报",
      "验证邮箱",
    ]) {
      expect(text, `FAQ is missing ${topic}`).toContain(topic);
    }
    expect(text).not.toMatch(/支持所有平台|无水印|自动转写|永久免费|DRM 破解|100% 成功/);
  });
});

describe("site navigation", () => {
  const headerLinks = (document: Document): [string, string][] =>
    [...document.querySelectorAll("header nav a")].map((node) => [
      textOf(node),
      node.getAttribute("href") ?? "",
    ]);

  it("keeps the header, footer and skip link on every marketing page", () => {
    const document = page("features.html");
    const mainNav = new Map(headerLinks(document));
    expect(mainNav.get("首页")).toBe("/");
    expect(mainNav.get("功能")).toBe("/features");
    expect(mainNav.get("使用指南")).toBe("/guide");
    expect(mainNav.get("FAQ")).toBe("/faq");
    expect(mainNav.get("文章")).toBe("/articles");
    expect(mainNav.get("价格")).toBe("/pricing");

    const footer = document.querySelector("footer");
    const footerLinks = new Map(
      [...(footer?.querySelectorAll("nav a") ?? [])].map((node) => [
        textOf(node),
        node.getAttribute("href") ?? "",
      ]),
    );
    expect(footerLinks.get("功能")).toBe("/features");
    expect(footerLinks.get("指南")).toBe("/guide");
    expect(footerLinks.get("FAQ")).toBe("/faq");
    expect(footerLinks.get("文章")).toBe("/articles");
    expect(footerLinks.get("价格")).toBe("/pricing");
    expect(footerLinks.get("条款")).toBe("/terms");
    expect(footerLinks.get("举报")).toBe("/terms#report");
    expect(textOf(footer)).toContain("仅限个人备份或已获授权内容");

    // Skip link is the first focusable element and targets the main landmark.
    const firstAnchor = document.body.querySelector("a");
    expect(textOf(firstAnchor)).toBe("跳到主要内容");
    expect(firstAnchor?.getAttribute("href")).toBe("#main-content");
    const main = document.querySelector("main#main-content");
    expect(main?.getAttribute("tabindex")).toBe("-1");
  });

  it("points every header and footer link at a page this build produced", () => {
    const document = page("features.html");
    const builtPaths = new Set(build.pages.map((entry) => entry.path));
    // The auth entry is a private SPA route, not a prerendered Marketing Page.
    const appPaths = new Set(["/login"]);
    const anchors = [
      ...document.querySelectorAll("header nav a, footer nav a"),
    ];

    for (const anchor of anchors) {
      const href = anchor.getAttribute("href") ?? "";
      const pathOnly = href.split("#")[0].split("?")[0] || "/";
      expect(builtPaths.has(pathOnly) || appPaths.has(pathOnly), `${textOf(anchor)} -> ${href}`).toBe(
        true,
      );
    }
  });

  it("keeps heading levels continuous on every marketing page", () => {
    for (const file of ["index.html", "guide.html", "faq.html", "features.html"]) {
      const levels = headingLevels(page(file));
      expect(levels[0], file).toBe(1);
      for (let index = 1; index < levels.length; index += 1) {
        expect(levels[index] - levels[index - 1], `${file} heading ${index}`).toBeLessThanOrEqual(1);
      }
    }
  });
});
