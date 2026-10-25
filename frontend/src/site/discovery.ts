/**
 * Discovery artifacts: ``sitemap.xml``, ``robots.txt`` and ``llms.txt`` built
 * from the same public descriptors and published Article collection as the
 * prerendered pages. Pure string builders plus one writer, so the build script
 * and the artifact tests share exactly one implementation.
 */
import { writeFile } from "node:fs/promises";
import path from "node:path";

import { FREE_DAILY_ANALYSIS_LABEL, PRICE_BENEFIT, PRICE_HEADLINE } from "@/lib/billing";
import type { ArticleCollection } from "@/site/articles";
import { APP_SHELL_PATH, PRIVATE_APP_ROUTES } from "@/site/routes";
import {
  SITE_NAME,
  canonicalUrl,
  indexableDescriptors,
  type PageDescriptor,
} from "@/site/seo";

export const SITEMAP_FILE = "sitemap.xml";
export const ROBOTS_FILE = "robots.txt";
export const LLMS_FILE = "llms.txt";

/** Crawl exclusions shared by robots.txt; private app surface only. */
export const DISALLOWED_PATHS = [
  "/api/",
  ...PRIVATE_APP_ROUTES,
  APP_SHELL_PATH,
] as const;

/**
 * Any loopback host means a test/local deployment: crawl everything is wrong,
 * so robots.txt forbids all and the build warns instead of publishing a site
 * that could be indexed under ``localhost``. The host is parsed once with the
 * same URL parser used to validate the origin; ``127.0.0.0/8``, ``0.0.0.0``,
 * IPv6 ``::1`` and ``*.localhost`` are all treated as loopback.
 */
export function isLoopbackOrigin(origin: string): boolean {
  let hostname: string;
  try {
    hostname = new URL(origin).hostname;
  } catch {
    return false;
  }
  const host = hostname.replace(/^\[|\]$/g, "").toLowerCase();
  if (host === "localhost" || host.endsWith(".localhost")) return true;
  if (host === "::1" || host === "0.0.0.0") return true;
  return /^127\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(host);
}

function escapeXml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/**
 * Every indexable page exactly once, in registry order (home first, marketing
 * pages, then the Article list and each published Article newest first). A
 * public page that opts out of indexing is deliberately not advertised here —
 * the explicit indexable predicate, not a robots-string coincidence.
 */
export function buildSitemapXml(
  origin: string,
  descriptors: readonly PageDescriptor[],
): string {
  const lines = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
  ];
  for (const descriptor of indexableDescriptors(descriptors)) {
    lines.push("  <url>");
    lines.push(`    <loc>${escapeXml(canonicalUrl(origin, descriptor.path))}</loc>`);
    // Article descriptors already resolve ``updated`` to ``published``.
    if (descriptor.article) {
      lines.push(`    <lastmod>${escapeXml(descriptor.article.updated)}</lastmod>`);
    }
    lines.push("  </url>");
  }
  lines.push("</urlset>");
  return `${lines.join("\n")}\n`;
}

export function buildRobotsTxt(origin: string): string {
  const lines = ["User-agent: *"];
  if (isLoopbackOrigin(origin)) {
    lines.push("Disallow: /");
  } else {
    lines.push("Allow: /");
    for (const route of DISALLOWED_PATHS) lines.push(`Disallow: ${route}`);
  }
  lines.push("", `Sitemap: ${canonicalUrl(origin, `/${SITEMAP_FILE}`)}`);
  return `${lines.join("\n")}\n`;
}

/** What llms.txt says about each indexable marketing page, in reading order. */
const LLMS_KEY_PAGES: readonly { path: string; label: string; summary: string }[] = [
  {
    path: "/",
    label: "首页",
    summary: "粘贴 B 站或 YouTube 页面地址，解析后下载文件、导出 Subtitle 或发起 Analysis。",
  },
  {
    path: "/features",
    label: "功能",
    summary: "视频解析、文件 Download、Subtitle 导出、AI 摘要、思维导图与历史记录的能力与限制。",
  },
  {
    path: "/guide",
    label: "指南",
    summary: "从复制页面地址到 Subtitle、Download 与 Analysis 的三步操作与排查方法。",
  },
  {
    path: "/faq",
    label: "FAQ",
    summary: "平台支持、免费 Quota、VIP 价格、Subtitle、DRM、文件保留与举报入口。",
  },
  {
    path: "/articles",
    label: "文章",
    summary: "B 站与 YouTube 字幕导出、视频学习笔记与 AI 摘要的实操教程。",
  },
  {
    path: "/pricing",
    label: "价格",
    summary: `免费 Account ${FREE_DAILY_ANALYSIS_LABEL}；VIP 会员 ${PRICE_HEADLINE}，${PRICE_BENEFIT}。`,
  },
  {
    path: "/terms",
    label: "条款",
    summary: "合规使用、禁止用途、临时文件与下载链接的保留策略，以及版权举报表单。",
  },
];

const LLMS_SUMMARY =
  "免费在线工具：粘贴 B 站或 YouTube 页面地址，下载文件、导出 SRT/VTT/TXT 字幕，并基于字幕生成 AI 摘要与思维导图；不做 ASR，没有字幕的视频无法生成 Analysis。";

/**
 * llmstxt.org shape: H1, blockquote summary, link sections, then the price and
 * usage boundaries an answer engine may quote. Only public canonical URLs.
 */
export function buildLlmsTxt(
  origin: string,
  descriptors: readonly PageDescriptor[],
  articles: ArticleCollection,
): string {
  const publicPaths = new Set(
    indexableDescriptors(descriptors).map((descriptor) => descriptor.path),
  );
  const lines = ["# " + SITE_NAME, "", `> ${LLMS_SUMMARY}`, "", "## 关键页面", ""];
  for (const page of LLMS_KEY_PAGES) {
    if (!publicPaths.has(page.path)) continue;
    lines.push(`- [${page.label}](${canonicalUrl(origin, page.path)})：${page.summary}`);
  }

  lines.push("", "## 文章", "");
  for (const article of articles.published) {
    const url = canonicalUrl(origin, `/articles/${article.slug}`);
    lines.push(`- [${article.title}](${url})：${article.description}`);
  }

  lines.push(
    "",
    "## 价格与使用边界",
    "",
    `- 免费 Account ${FREE_DAILY_ANALYSIS_LABEL}；VIP 会员 ${PRICE_HEADLINE}，${PRICE_BENEFIT}。`,
    "- 单视频最长 2 小时，最大 2 GB。",
    "- 服务端文件最多保留 1 小时，下载链接 15 分钟内有效。",
    "- 不做 ASR：没有 Subtitle 的视频不能导出 Subtitle，也不能发起 Analysis。",
    "- Analysis 私有：结果仅本人可见，不生成公开页面。",
    `- 不支持播放列表、直播、DRM 与会员专属内容；举报入口见[使用条款](${canonicalUrl(origin, "/terms")}#report)。`,
    "",
  );
  return lines.join("\n");
}

export interface DiscoveryArtifacts {
  sitemap: string;
  robots: string;
  llms: string;
}

export function buildDiscoveryArtifacts(
  origin: string,
  descriptors: readonly PageDescriptor[],
  articles: ArticleCollection,
): DiscoveryArtifacts {
  return {
    sitemap: buildSitemapXml(origin, descriptors),
    robots: buildRobotsTxt(origin),
    llms: buildLlmsTxt(origin, descriptors, articles),
  };
}

/** Write the three root artifacts; a loopback origin warns once, loudly. */
export async function writeDiscoveryArtifacts(
  outputDir: string,
  artifacts: DiscoveryArtifacts,
  origin: string,
): Promise<void> {
  if (isLoopbackOrigin(origin)) {
    console.warn(
      `[discovery] loopback origin ${origin}: robots.txt disallows all crawlers (Disallow: /) so a local build cannot be indexed.`,
    );
  }
  await Promise.all([
    writeFile(path.join(outputDir, SITEMAP_FILE), artifacts.sitemap, "utf8"),
    writeFile(path.join(outputDir, ROBOTS_FILE), artifacts.robots, "utf8"),
    writeFile(path.join(outputDir, LLMS_FILE), artifacts.llms, "utf8"),
  ]);
}
