/**
 * Site-wide internal link audit: after every page is generated, each internal
 * href (HTML CTAs, navigation, Article Markdown) must resolve to a produced
 * public page, an allowed private app route, or a real anchor on the target
 * page. Broken links fail the build naming the source page and the target.
 */
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import { buildSite } from "@/site/build-site";
import { renderRoute } from "@/site/entry-server";
import { defaultArticleSources } from "@/site/article-sources";
import type { ArticleSource } from "@/site/articles";
import { validateSiteLinks } from "@/site/site-links";
import { INDEX_ROBOTS, pageDescriptors, type PageDescriptor } from "@/site/seo";

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

afterEach(async () => {
  await Promise.all(createdDirs.splice(0).map((dir) => rm(dir, { recursive: true, force: true })));
});

async function tempDir(): Promise<string> {
  const dir = await mkdtemp(path.join(tmpdir(), "seo-links-"));
  createdDirs.push(dir);
  return dir;
}

function fixtureDescriptor(path: string): PageDescriptor {
  return {
    name: "link-check",
    path,
    title: "坏链检查页面",
    description:
      "这是用于全站内链校验测试的公开页面描述，长度需要落在七十到一百六十个字符之间，以便通过搜索引擎描述符校验；页面正文只包含一个指向目标地址的链接。",
    robots: INDEX_ROBOTS,
    ogType: "website",
  };
}

async function buildWithFixtureLink(href: string): Promise<void> {
  const outDir = await tempDir();
  await buildSite({
    origin: ORIGIN,
    descriptors: [...pageDescriptors, fixtureDescriptor("/link-check")],
    shellHtml: SHELL,
    outputDir: outDir,
    renderRoute: (routePath, articles) =>
      routePath === "/link-check"
        ? { html: `<h1>坏链检查</h1><p><a href="${href}">目标链接</a></p>` }
        : renderRoute(routePath, articles),
  });
}

describe("validateSiteLinks", () => {
  it("accepts generated pages, allowed app routes, anchors and external protocols", () => {
    const pages = [
      {
        path: "/",
        html: [
          '<div id="main-content">',
          '<a href="#main-content">跳到主要内容</a>',
          '<a href="/terms#report">举报</a>',
          '<a href="/login?next=/account">登录</a>',
          '<a href="/analyses/abc-123">分析</a>',
          '<a href="https://example.org/x">外链</a>',
          '<a href="mailto:hello@example.org">邮件</a>',
          '<a href="tel:+100">电话</a>',
          "</div>",
        ].join(""),
      },
      { path: "/terms", html: '<section id="report"><h1>使用条款</h1></section>' },
    ];

    expect(() => validateSiteLinks({ pages })).not.toThrow();
  });

  it("names the source page and the target when a route does not exist", () => {
    const pages = [{ path: "/features", html: '<a href="/missing-page">坏链</a>' }];

    const run = () => validateSiteLinks({ pages });
    expect(run).toThrow(/\/features/);
    expect(run).toThrow(/\/missing-page/);
  });

  it("names the source, target and missing anchor", () => {
    const pages = [
      { path: "/features", html: '<a href="/terms#no-such-anchor">坏链</a>' },
      { path: "/terms", html: '<section id="report"></section>' },
    ];

    const run = () => validateSiteLinks({ pages });
    expect(run).toThrow(/\/features/);
    expect(run).toThrow(/\/terms#no-such-anchor/);
    expect(run).toThrow(/no-such-anchor/);
  });

  it("rejects unknown same-page anchors", () => {
    const pages = [{ path: "/faq", html: '<div id="known"></div><a href="#unknown">坏链</a>' }];

    expect(() => validateSiteLinks({ pages })).toThrow(/unknown/);
  });

  it("rejects javascript: URLs in generated output", () => {
    const pages = [{ path: "/features", html: '<a href="javascript:alert(1)">坏链</a>' }];

    expect(() => validateSiteLinks({ pages })).toThrow(/javascript:/i);
  });

  it("validates Article Markdown links against the produced pages", () => {
    const pages = [
      { path: "/articles", html: "" },
      { path: "/terms", html: '<section id="report"></section>' },
    ];

    expect(() =>
      validateSiteLinks({
        pages,
        markdown: [
          {
            path: "/articles/draft-article",
            source: "[条款](/terms#report) 与 [不存在](/articles/not-published)",
          },
        ],
      }),
    ).toThrow(/\/articles\/draft-article[\s\S]*\/articles\/not-published/);
  });
});

describe("buildSite internal links", () => {
  it("passes for the real content, including /terms#report", async () => {
    await expect(buildWithFixtureLink("/terms#report")).resolves.toBeUndefined();
  });

  it("fails naming the fixture source page and the missing target", async () => {
    const run = buildWithFixtureLink("/missing-page");
    await expect(run).rejects.toThrow(/\/link-check/);
    await expect(buildWithFixtureLink("/missing-page")).rejects.toThrow(/\/missing-page/);
  });

  it("fails with the missing anchor when a generated page lacks it", async () => {
    const run = buildWithFixtureLink("/terms#no-such-anchor");
    await expect(run).rejects.toThrow(/\/link-check/);
    await expect(buildWithFixtureLink("/terms#no-such-anchor")).rejects.toThrow(/no-such-anchor/);
  });

  it("fails when a page links to a draft Article", async () => {
    const outDir = await tempDir();
    const draft: ArticleSource = {
      fileName: "draft-article.md",
      source: [
        "---",
        "title: 草稿：不应被链接的测试文章",
        "description: 这是一段用于测试草稿内链失败的文章描述，覆盖七十到一百六十个字符的长度要求，确保描述足够详细完整；草稿页面不应存在，也不应被任何页面链接指向，否则构建必须失败。",
        "published: 2026-10-01",
        "draft: true",
        "---",
        "",
        "这是一段用于测试草稿内链的文章正文，包含足够多的字符以便通过构建期长度校验。".repeat(25),
        "",
      ].join("\n"),
    };

    const error = await buildSite({
      origin: ORIGIN,
      descriptors: [...pageDescriptors, fixtureDescriptor("/link-check")],
      articleSources: [...defaultArticleSources, draft],
      shellHtml: SHELL,
      outputDir: outDir,
      renderRoute: (routePath, articles) =>
        routePath === "/link-check"
          ? { html: '<h1>坏链检查</h1><a href="/articles/draft-article">草稿</a>' }
          : renderRoute(routePath, articles),
    }).catch((reason: Error) => reason);

    expect(error).toBeInstanceOf(Error);
    expect((error as Error).message).toMatch(/\/link-check/);
    expect((error as Error).message).toMatch(/\/articles\/draft-article/);
  });
});
