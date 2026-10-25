/**
 * The page registry and SEO descriptors: the single source of truth shared by
 * the prerender build and the client router (ADR-0005).
 *
 * This module is deliberately DOM-free so it can be imported from the browser
 * bundle, plain Node (prerender script) and tests. The only import is the pure
 * billing constants module, which keeps the visible price and structured data
 * on one source.
 */
import { MONTHLY_PRICE_USD, PRICE_BENEFIT, PRICE_HEADLINE } from "@/lib/billing";
import {
  DESCRIPTION_MAX_LENGTH,
  DESCRIPTION_MIN_LENGTH,
  MAX_DOCUMENT_TITLE_LENGTH,
  reviewArticleDates,
} from "@/site/content-limits";
import { faqItems } from "@/site/faq-content";
import { guideSteps } from "@/site/guide-content";

export const SITE_NAME = "AI 视频学习助手";
export const DEFAULT_SHARE_IMAGE = "/brand/share-card.png";
/** Square brand icon: apple-touch-icon and the Organization logo. */
export const BRAND_ICON = "/brand/icon-512.png";
export const SHARE_IMAGE_WIDTH = 1200;
export const SHARE_IMAGE_HEIGHT = 630;
export const INDEX_ROBOTS = "index,follow,max-image-preview:large";
export const NOINDEX_ROBOTS = "noindex,nofollow";
export const DEFAULT_DEV_ORIGIN = "http://localhost:5173";

export type RobotsDirective = typeof INDEX_ROBOTS | typeof NOINDEX_ROBOTS;
export type OgType = "website" | "article";

export interface Breadcrumb {
  name: string;
  /** Canonical path of the breadcrumb target ("/" for the home page). */
  path: string;
}

/** Article-only head fields; dates come from frontmatter, never from the clock. */
export interface ArticleHeadMeta {
  published: string;
  updated: string;
  tags?: readonly string[];
}

export type JsonLdNode = Record<string, unknown>;

export interface JsonLdContext {
  descriptor: PageDescriptor;
  origin: string;
  canonicalUrl: string;
  siteName: string;
  imageUrl: string;
}

export interface PageDescriptor {
  /** Route name, used by the client router to resolve the descriptor. */
  name: string;
  /** Canonical path. Public pages only; private entries keep their route pattern. */
  path: string;
  title: string;
  description: string;
  robots: RobotsDirective;
  ogType: OgType;
  /** Site-relative path (or absolute URL) of the 1200x630 share card. */
  image?: string;
  imageAlt?: string;
  breadcrumbs?: Breadcrumb[];
  /** Set for Article pages: drives ``article:*`` Open Graph tags. */
  article?: ArticleHeadMeta;
  /** Extra JSON-LD nodes. A BreadcrumbList is added when breadcrumbs exist. */
  jsonLd?: (context: JsonLdContext) => JsonLdNode[];
}

export interface HeadTag {
  tag: "title" | "meta" | "link" | "script";
  attrs: Record<string, string>;
  text?: string;
}

export class SeoDescriptorError extends Error {
  constructor(route: string, reason: string) {
    super(`SEO descriptor for route ${route}: ${reason}`);
    this.name = "SeoDescriptorError";
  }
}

/** Managed nodes carry this marker so runtime updates replace instead of append. */
export const MANAGED_ATTRIBUTE = "data-seo-managed";

export function isPublicDescriptor(descriptor: PageDescriptor): boolean {
  return descriptor.robots === INDEX_ROBOTS;
}

/**
 * Build-time origin. Vite replaces this exact ``import.meta.env.VITE_SITE_ORIGIN``
 * property access with the configured string at build time; aliasing
 * ``import.meta`` would defeat that static replacement and leave the runtime
 * falling back to the dev origin. Plain Node has no ``import.meta.env``, so the
 * access throws and is caught.
 */
function viteSiteOrigin(): string | undefined {
  try {
    return import.meta.env.VITE_SITE_ORIGIN;
  } catch {
    return undefined;
  }
}

/** Raised at build time when ``VITE_SITE_ORIGIN`` is not a bare http(s) origin. */
export class SiteOriginError extends Error {
  readonly value: string;

  constructor(value: string, reason: string) {
    super(
      `Invalid VITE_SITE_ORIGIN "${value}": ${reason}. ` +
        "Use a bare absolute origin such as https://example.com (no credentials, path, query, hash or trailing slash).",
    );
    this.name = "SiteOriginError";
    this.value = value;
  }
}

function assertBareOrigin(raw: string): string {
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    throw new SiteOriginError(raw, "it is not an absolute URL with a host");
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new SiteOriginError(raw, `only http(s) is allowed, got "${url.protocol}"`);
  }
  if (!url.hostname) {
    throw new SiteOriginError(raw, "the host is empty");
  }
  if (url.username || url.password) {
    throw new SiteOriginError(raw, "credentials are not allowed");
  }
  if (url.pathname !== "/") {
    throw new SiteOriginError(raw, `a path is not allowed (got "${url.pathname}")`);
  }
  if (url.search) {
    throw new SiteOriginError(raw, `a query is not allowed (got "${url.search}")`);
  }
  if (url.hash) {
    throw new SiteOriginError(raw, `a hash is not allowed (got "${url.hash}")`);
  }
  if (raw.endsWith("/")) {
    throw new SiteOriginError(raw, "a trailing slash is not allowed");
  }
  return url.origin;
}

/**
 * The origin baked into canonical/OG/sitemap at build time. Unset means local
 * Vite development, which falls back loudly instead of shipping a broken
 * relative canonical.
 */
export function resolveSiteOrigin(value: string | undefined = viteSiteOrigin()): string {
  const trimmed = value?.trim() ?? "";
  if (!trimmed) {
    console.warn(`[seo] VITE_SITE_ORIGIN is not set; falling back to ${DEFAULT_DEV_ORIGIN}.`);
    return DEFAULT_DEV_ORIGIN;
  }
  return assertBareOrigin(trimmed);
}

export function canonicalUrl(origin: string, path: string): string {
  const base = origin.replace(/\/+$/, "");
  if (path === "/") return `${base}/`;
  return `${base}${path.startsWith("/") ? path : `/${path}`}`;
}

export function documentTitle(descriptor: PageDescriptor): string {
  return `${descriptor.title} · ${SITE_NAME}`;
}

function imageUrlFor(descriptor: PageDescriptor, origin: string): string {
  const image = descriptor.image ?? DEFAULT_SHARE_IMAGE;
  return /^https?:\/\//.test(image) ? image : canonicalUrl(origin, image);
}

function jsonLdContext(descriptor: PageDescriptor, origin: string): JsonLdContext {
  return {
    descriptor,
    origin: origin.replace(/\/+$/, ""),
    canonicalUrl: canonicalUrl(origin, descriptor.path),
    siteName: SITE_NAME,
    imageUrl: imageUrlFor(descriptor, origin),
  };
}

export function webPageNode(context: JsonLdContext): JsonLdNode {
  const { descriptor, canonicalUrl: url, origin } = context;
  return {
    "@type": "WebPage",
    "@id": `${url}#webpage`,
    url,
    name: documentTitle(descriptor),
    description: descriptor.description,
    inLanguage: "zh-CN",
    isPartOf: {
      "@type": "WebSite",
      "@id": `${origin}/#website`,
      name: SITE_NAME,
      url: `${origin}/`,
    },
    publisher: { "@id": `${origin}/#organization` },
    primaryImageOfPage: { "@type": "ImageObject", url: context.imageUrl },
  };
}

/**
 * The site entity itself: `/` declares the WebSite that every WebPage is part
 * of. ``url`` is the origin root so the whole site shares one stable @id.
 */
export function websiteNode(context: JsonLdContext): JsonLdNode {
  const { descriptor, origin } = context;
  return {
    "@type": "WebSite",
    "@id": `${origin}/#website`,
    url: `${origin}/`,
    name: SITE_NAME,
    description: descriptor.description,
    inLanguage: "zh-CN",
    publisher: { "@id": `${origin}/#organization` },
  };
}

/**
 * The one paid plan as structured data. The price is the same constant the
 * visible headline renders; no rating or review nodes are invented.
 */
export function pricingApplicationNode(context: JsonLdContext): JsonLdNode {
  const url = context.canonicalUrl;
  return {
    "@type": "SoftwareApplication",
    "@id": `${url}#software`,
    name: SITE_NAME,
    applicationCategory: "MultimediaApplication",
    operatingSystem: "Web",
    url,
    description: context.descriptor.description,
    featureList: [PRICE_BENEFIT, "视频解析与 Download", "Subtitle 导出"],
    offers: {
      "@type": "Offer",
      "@id": `${url}#offer`,
      price: MONTHLY_PRICE_USD,
      priceCurrency: "USD",
      availability: "https://schema.org/InStock",
      url,
    },
  };
}

/**
 * The site-level Organization: publisher/owner of every page and article.
 * ``sameAs`` is intentionally absent — there are no real social profiles yet.
 */
export function organizationNode(context: JsonLdContext): JsonLdNode {
  const { origin } = context;
  const logoUrl = `${origin}${BRAND_ICON}`;
  return {
    "@type": "Organization",
    "@id": `${origin}/#organization`,
    name: SITE_NAME,
    url: `${origin}/`,
    logo: {
      "@type": "ImageObject",
      "@id": `${logoUrl}#image`,
      url: logoUrl,
      contentUrl: logoUrl,
      width: 512,
      height: 512,
      caption: SITE_NAME,
    },
  };
}

export function breadcrumbListNode(context: JsonLdContext): JsonLdNode {
  const { descriptor, canonicalUrl: url, origin } = context;
  return {
    "@type": "BreadcrumbList",
    "@id": `${url}#breadcrumb`,
    itemListElement: (descriptor.breadcrumbs ?? []).map((crumb, index) => ({
      "@type": "ListItem",
      position: index + 1,
      name: crumb.name,
      item: canonicalUrl(origin, crumb.path),
    })),
  };
}

/**
 * `/guide`: the HowTo steps come from the same module the visible ordered list
 * renders, so name/text are verbatim-identical by construction.
 */
export function howToNode(context: JsonLdContext): JsonLdNode {
  const url = context.canonicalUrl;
  return {
    "@type": "HowTo",
    "@id": `${url}#howto`,
    name: "使用指南：从页面地址到 AI 分析",
    description: context.descriptor.description,
    inLanguage: "zh-CN",
    step: guideSteps.map((step, index) => ({
      "@type": "HowToStep",
      position: index + 1,
      name: step.title,
      text: step.text,
    })),
  };
}

/** `/faq`: every Question/Answer is the exact string the page renders. */
export function faqPageNode(context: JsonLdContext): JsonLdNode {
  const url = context.canonicalUrl;
  return {
    "@type": "FAQPage",
    "@id": `${url}#faq`,
    url,
    name: "常见问题",
    inLanguage: "zh-CN",
    mainEntity: faqItems.map((item) => ({
      "@type": "Question",
      name: item.question,
      acceptedAnswer: { "@type": "Answer", text: item.answer },
    })),
  };
}

function meta(attrs: Record<string, string>): HeadTag {
  return { tag: "meta", attrs: { ...attrs, [MANAGED_ATTRIBUTE]: "" } };
}

const ARTICLE_TYPES = new Set(["Article", "BlogPosting", "NewsArticle", "TechArticle"]);

/** Article descriptors may omit publisher; the site Organization fills it in. */
function isArticleNode(node: JsonLdNode): boolean {
  const type = node["@type"];
  if (typeof type === "string") return ARTICLE_TYPES.has(type);
  if (Array.isArray(type)) {
    return type.some((item) => typeof item === "string" && ARTICLE_TYPES.has(item));
  }
  return false;
}

/**
 * The pure head contract: descriptor + origin -> ordered tag list.
 * Public pages get title/description/canonical/robots/OG/Twitter/JSON-LD;
 * private pages get only an unindexed title and robots directive.
 */
export function headTags(descriptor: PageDescriptor, origin: string): HeadTag[] {
  const title = documentTitle(descriptor);
  const tags: HeadTag[] = [
    { tag: "title", attrs: { [MANAGED_ATTRIBUTE]: "" }, text: title },
  ];

  if (!isPublicDescriptor(descriptor)) {
    tags.push(meta({ name: "robots", content: NOINDEX_ROBOTS }));
    return tags;
  }

  const url = canonicalUrl(origin, descriptor.path);
  const context = jsonLdContext(descriptor, origin);
  const image = context.imageUrl;
  const imageAlt =
    descriptor.imageAlt ?? `${SITE_NAME}：解析公开视频，下载文件、导出字幕并生成 AI 摘要`;

  tags.push(
    meta({ name: "description", content: descriptor.description }),
    { tag: "link", attrs: { rel: "canonical", href: url, [MANAGED_ATTRIBUTE]: "" } },
    meta({ name: "robots", content: INDEX_ROBOTS }),
    meta({ property: "og:type", content: descriptor.ogType }),
    meta({ property: "og:site_name", content: SITE_NAME }),
    meta({ property: "og:title", content: title }),
    meta({ property: "og:description", content: descriptor.description }),
    meta({ property: "og:url", content: url }),
    meta({ property: "og:image", content: image }),
    meta({ property: "og:image:width", content: String(SHARE_IMAGE_WIDTH) }),
    meta({ property: "og:image:height", content: String(SHARE_IMAGE_HEIGHT) }),
    meta({ property: "og:image:alt", content: imageAlt }),
    meta({ property: "og:locale", content: "zh_CN" }),
  );

  if (descriptor.article) {
    tags.push(
      meta({ property: "article:published_time", content: descriptor.article.published }),
      meta({ property: "article:modified_time", content: descriptor.article.updated }),
    );
    for (const tag of descriptor.article.tags ?? []) {
      tags.push(meta({ property: "article:tag", content: tag }));
    }
  }

  tags.push(
    meta({ name: "twitter:card", content: "summary_large_image" }),
    meta({ name: "twitter:title", content: title }),
    meta({ name: "twitter:description", content: descriptor.description }),
    meta({ name: "twitter:image", content: image }),
    meta({ name: "twitter:image:alt", content: imageAlt }),
  );

  const nodes = descriptor.jsonLd?.(context) ?? [];
  if (descriptor.breadcrumbs?.length) nodes.push(breadcrumbListNode(context));
  const organization = organizationNode(context);
  const organizationId = organization["@id"] as string;
  if (!nodes.some((node) => node["@id"] === organizationId)) nodes.push(organization);
  for (const node of nodes) {
    if (isArticleNode(node) && node.publisher === undefined) {
      node.publisher = { "@type": "Organization", "@id": organizationId };
    }
  }
  if (nodes.length > 0) {
    const payload = JSON.stringify({ "@context": "https://schema.org", "@graph": nodes });
    tags.push({
      tag: "script",
      attrs: { type: "application/ld+json", [MANAGED_ATTRIBUTE]: "" },
      text: payload.replace(/</g, "\\u003c"),
    });
  }

  return tags;
}

function escapeAttribute(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function escapeText(value: string): string {
  return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

/** Serialize the head contract for the static shell; the runtime builds the DOM. */
export function renderHeadHtml(descriptor: PageDescriptor, origin: string): string {
  return headTags(descriptor, origin)
    .map((tag) => {
      const attrs = Object.entries(tag.attrs)
        .map(([key, value]) => (value === "" ? key : `${key}="${escapeAttribute(value)}"`))
        .join(" ");
      const open = attrs ? `<${tag.tag} ${attrs}>` : `<${tag.tag}>`;
      if (tag.tag === "title") return `${open}${escapeText(tag.text ?? "")}</title>`;
      if (tag.tag === "script") return `${open}${tag.text ?? ""}</script>`;
      return open;
    })
    .join("\n    ");
}

/**
 * Validate the registry before rendering. Any violation names the route so the
 * build fails with an actionable message.
 */
export function validateDescriptors(descriptors: readonly PageDescriptor[]): void {
  const names = new Set<string>();
  const paths = new Set<string>();
  const titles = new Set<string>();
  const descriptions = new Set<string>();

  for (const descriptor of descriptors) {
    const route = descriptor.path || descriptor.name;
    if (!descriptor.name) throw new SeoDescriptorError(route, "missing route name");
    if (names.has(descriptor.name)) {
      throw new SeoDescriptorError(route, `duplicate route name "${descriptor.name}"`);
    }
    names.add(descriptor.name);

    if (!descriptor.title?.trim()) throw new SeoDescriptorError(route, "missing title");
    if (!descriptor.description?.trim()) throw new SeoDescriptorError(route, "missing description");
    if (descriptor.robots !== INDEX_ROBOTS && descriptor.robots !== NOINDEX_ROBOTS) {
      throw new SeoDescriptorError(route, `invalid robots directive "${descriptor.robots}"`);
    }
    if (descriptor.ogType !== "website" && descriptor.ogType !== "article") {
      throw new SeoDescriptorError(route, `invalid og:type "${descriptor.ogType}"`);
    }

    if (descriptor.article) {
      const { published, updated } = descriptor.article;
      if (descriptor.ogType !== "article") {
        throw new SeoDescriptorError(route, "article dates require og:type article");
      }
      const dateIssue = reviewArticleDates(published, updated);
      if (dateIssue) {
        throw new SeoDescriptorError(route, `article ${dateIssue.field} ${dateIssue.reason}`);
      }
    }

    if (!isPublicDescriptor(descriptor)) continue;

    if (descriptor.path !== "/" && descriptor.path.endsWith("/")) {
      throw new SeoDescriptorError(route, "public path must not end with a slash");
    }
    if (!descriptor.path.startsWith("/")) {
      throw new SeoDescriptorError(route, "public path must start with /");
    }
    if (paths.has(descriptor.path)) {
      throw new SeoDescriptorError(route, `duplicate public path "${descriptor.path}"`);
    }
    paths.add(descriptor.path);

    const fullTitle = documentTitle(descriptor);
    if (fullTitle.length > MAX_DOCUMENT_TITLE_LENGTH) {
      throw new SeoDescriptorError(
        route,
        `title is ${fullTitle.length} characters (max ${MAX_DOCUMENT_TITLE_LENGTH})`,
      );
    }
    if (titles.has(fullTitle)) throw new SeoDescriptorError(route, `duplicate title "${fullTitle}"`);
    titles.add(fullTitle);

    const length = descriptor.description.length;
    if (length < DESCRIPTION_MIN_LENGTH || length > DESCRIPTION_MAX_LENGTH) {
      throw new SeoDescriptorError(
        route,
        `description is ${length} characters (expected ${DESCRIPTION_MIN_LENGTH}-${DESCRIPTION_MAX_LENGTH})`,
      );
    }
    if (descriptions.has(descriptor.description)) {
      throw new SeoDescriptorError(route, "duplicate description");
    }
    descriptions.add(descriptor.description);
  }
}

const HOME_DESCRIPTION =
  "AI 视频学习助手首页：粘贴 B 站或 YouTube 页面地址，完成视频下载、导出 SRT/VTT/TXT 字幕，并基于字幕生成 AI 摘要与思维导图；免费账号每日 3 次 Analysis。";
const FEATURES_DESCRIPTION =
  "AI 视频学习助手功能总览：解析 B 站与 YouTube 页面地址、下载视频、导出字幕、生成 AI 摘要与思维导图，并说明 Analysis 历史、免费 Quota 与 VIP 会员的边界。";
const GUIDE_DESCRIPTION =
  "使用指南：三步解析 B 站或 YouTube 页面地址，下载视频或导出 SRT/VTT/TXT 字幕，再登录生成 AI 摘要与思维导图；并说明平台差异、DRM、链接过期、Quota 与邮箱验证的排查方法。";
const FAQ_DESCRIPTION = `AI 视频学习助手常见问题：支持的 Platform 与抖音灰度、免费每日 3 次 Analysis、VIP ${PRICE_HEADLINE}、无 Subtitle 不能 Analysis、不做 ASR、文件保留 1 小时与下载链接 15 分钟有效。`;
const PRICING_DESCRIPTION = `AI 视频学习助手价格页：免费账号每日 3 次 Analysis，VIP 会员 ${PRICE_HEADLINE}（USD）解锁 ${PRICE_BENEFIT}；按月自动续费，可随时在订阅管理中取消，实际扣款以 Stripe 结账页为准。`;
const TERMS_DESCRIPTION =
  "AI 视频学习助手使用条款：说明合规使用与禁止用途、临时文件与下载链接的保留策略、版权与投诉方式，并提供 /terms#report 举报表单的提交入口。";

const HOME_BREADCRUMB: Breadcrumb = { name: "首页", path: "/" };

/**
 * Route-name keyed registry. Public entries are prerendered to their own .html;
 * private entries only drive the runtime noindex head.
 */
export const pageDescriptors: readonly PageDescriptor[] = [
  {
    name: "home",
    path: "/",
    title: "视频下载、字幕导出与 AI 摘要",
    description: HOME_DESCRIPTION,
    robots: INDEX_ROBOTS,
    ogType: "website",
    image: DEFAULT_SHARE_IMAGE,
    jsonLd: (context) => [websiteNode(context), pricingApplicationNode(context)],
  },
  {
    name: "features",
    path: "/features",
    title: "功能：视频解析、字幕导出与 AI 分析",
    description: FEATURES_DESCRIPTION,
    robots: INDEX_ROBOTS,
    ogType: "website",
    image: DEFAULT_SHARE_IMAGE,
    imageAlt: "AI 视频学习助手功能总览",
    breadcrumbs: [HOME_BREADCRUMB, { name: "功能", path: "/features" }],
    jsonLd: (context) => [webPageNode(context)],
  },
  {
    name: "guide",
    path: "/guide",
    title: "使用指南：解析、下载与 AI 分析",
    description: GUIDE_DESCRIPTION,
    robots: INDEX_ROBOTS,
    ogType: "website",
    image: DEFAULT_SHARE_IMAGE,
    imageAlt: "AI 视频学习助手使用指南",
    breadcrumbs: [HOME_BREADCRUMB, { name: "使用指南", path: "/guide" }],
    jsonLd: (context) => [webPageNode(context), howToNode(context)],
  },
  {
    name: "faq",
    path: "/faq",
    title: "常见问题：平台、Quota 与价格",
    description: FAQ_DESCRIPTION,
    robots: INDEX_ROBOTS,
    ogType: "website",
    image: DEFAULT_SHARE_IMAGE,
    imageAlt: "AI 视频学习助手常见问题",
    breadcrumbs: [HOME_BREADCRUMB, { name: "常见问题", path: "/faq" }],
    jsonLd: (context) => [webPageNode(context), faqPageNode(context)],
  },
  {
    name: "pricing",
    path: "/pricing",
    title: "价格：免费 Quota 与 VIP 会员",
    description: PRICING_DESCRIPTION,
    robots: INDEX_ROBOTS,
    ogType: "website",
    image: DEFAULT_SHARE_IMAGE,
    breadcrumbs: [HOME_BREADCRUMB, { name: "升级会员", path: "/pricing" }],
    jsonLd: (context) => [
      { ...webPageNode(context), mainEntity: { "@id": `${context.canonicalUrl}#software` } },
      pricingApplicationNode(context),
    ],
  },
  {
    name: "terms",
    path: "/terms",
    title: "使用条款与举报",
    description: TERMS_DESCRIPTION,
    robots: INDEX_ROBOTS,
    ogType: "website",
    image: DEFAULT_SHARE_IMAGE,
    breadcrumbs: [HOME_BREADCRUMB, { name: "使用条款", path: "/terms" }],
    jsonLd: (context) => [webPageNode(context)],
  },
  {
    name: "login",
    path: "/login",
    title: "登录",
    description: "登录 AI 视频学习助手账号。",
    robots: NOINDEX_ROBOTS,
    ogType: "website",
  },
  {
    name: "account",
    path: "/account",
    title: "个人中心",
    description: "管理 AI 视频学习助手账号与订阅。",
    robots: NOINDEX_ROBOTS,
    ogType: "website",
  },
  {
    name: "verify-email",
    path: "/verify-email",
    title: "邮箱验证",
    description: "验证 AI 视频学习助手账号邮箱。",
    robots: NOINDEX_ROBOTS,
    ogType: "website",
  },
  {
    name: "analyses",
    path: "/analyses",
    title: "我的 Analysis",
    description: "查看 AI 视频学习助手的 Analysis 历史。",
    robots: NOINDEX_ROBOTS,
    ogType: "website",
  },
  {
    name: "analysis",
    path: "/analyses/:id",
    title: "AI 分析",
    description: "查看单个视频的 AI 分析结果。",
    robots: NOINDEX_ROBOTS,
    ogType: "website",
  },
  {
    name: "not-found",
    path: "*",
    title: "页面不存在",
    description: "请求的页面不存在。",
    robots: NOINDEX_ROBOTS,
    ogType: "website",
  },
];

const NOT_FOUND_DESCRIPTOR = pageDescriptors.find(
  (descriptor) => descriptor.name === "not-found",
) as PageDescriptor;

/** The unmatched-route descriptor; ``404.html`` is built from it. */
export const notFoundDescriptor: PageDescriptor = NOT_FOUND_DESCRIPTOR;

export function descriptorForRoute(name: string | symbol | null | undefined): PageDescriptor {
  if (typeof name === "string") {
    const match = pageDescriptors.find((descriptor) => descriptor.name === name);
    if (match) return match;
  }
  return NOT_FOUND_DESCRIPTOR;
}

export function publicDescriptors(
  descriptors: readonly PageDescriptor[] = pageDescriptors,
): PageDescriptor[] {
  return descriptors.filter(isPublicDescriptor);
}
