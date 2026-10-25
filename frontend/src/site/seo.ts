/**
 * The page registry and SEO descriptors: the single source of truth shared by
 * the prerender build and the client router (ADR-0005).
 *
 * This module is deliberately dependency-free and DOM-free so it can be
 * imported from the browser bundle, plain Node (prerender script) and tests.
 */

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
 * Build-time origin. Vite inlines ``VITE_SITE_ORIGIN``; plain Node reads the
 * property defensively (``import.meta.env`` is undefined there). Format
 * hardening is ticket #37 — this only trims trailing slashes.
 */
function viteSiteOrigin(): string | undefined {
  const meta = import.meta as ImportMeta & { env?: Record<string, string | undefined> };
  return meta.env?.VITE_SITE_ORIGIN;
}

export function resolveSiteOrigin(value: string | undefined = viteSiteOrigin()): string {
  const trimmed = value?.trim() ?? "";
  if (!trimmed) {
    console.warn(`[seo] VITE_SITE_ORIGIN is not set; falling back to ${DEFAULT_DEV_ORIGIN}.`);
    return DEFAULT_DEV_ORIGIN;
  }
  return trimmed.replace(/\/+$/, "") || DEFAULT_DEV_ORIGIN;
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
    if (fullTitle.length > 60) {
      throw new SeoDescriptorError(route, `title is ${fullTitle.length} characters (max 60)`);
    }
    if (titles.has(fullTitle)) throw new SeoDescriptorError(route, `duplicate title "${fullTitle}"`);
    titles.add(fullTitle);

    const length = descriptor.description.length;
    if (length < 70 || length > 160) {
      throw new SeoDescriptorError(
        route,
        `description is ${length} characters (expected 70-160)`,
      );
    }
    if (descriptions.has(descriptor.description)) {
      throw new SeoDescriptorError(route, "duplicate description");
    }
    descriptions.add(descriptor.description);
  }
}

const HOME_DESCRIPTION =
  "粘贴 B 站或 YouTube 页面地址，解析视频并下载文件、导出 SRT/VTT/TXT 字幕，再基于字幕生成简体中文 AI 摘要与思维导图，并查看个人 Analysis 历史。";
const FEATURES_DESCRIPTION =
  "AI 视频学习助手功能总览：解析 B 站与 YouTube 页面地址、下载视频、导出字幕、生成 AI 摘要与思维导图，并说明 Analysis 历史、免费 Quota 与 VIP 会员的边界。";
const PRICING_DESCRIPTION =
  "AI 视频学习助手 VIP 会员 $4.99/月，解锁 Analysis 不限次；免费账号每日 3 次，订阅由 Stripe 托管支付，可随时取消，实际扣款以结账页为准。";
const TERMS_DESCRIPTION =
  "AI 视频学习助手使用条款：说明服务范围与使用边界、禁止行为、举报与投诉入口、内容权利、文件留存与链接有效期，以及付费订阅、取消与退款相关约定。";

const HOME_BREADCRUMB: Breadcrumb = { name: "首页", path: "/" };

/**
 * Route-name keyed registry. Public entries are prerendered to their own .html;
 * private entries only drive the runtime noindex head.
 */
export const pageDescriptors: readonly PageDescriptor[] = [
  {
    name: "home",
    path: "/",
    title: "视频下载与 AI 分析",
    description: HOME_DESCRIPTION,
    robots: INDEX_ROBOTS,
    ogType: "website",
    image: DEFAULT_SHARE_IMAGE,
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
    name: "pricing",
    path: "/pricing",
    title: "升级 VIP 会员",
    description: PRICING_DESCRIPTION,
    robots: INDEX_ROBOTS,
    ogType: "website",
    image: DEFAULT_SHARE_IMAGE,
    breadcrumbs: [HOME_BREADCRUMB, { name: "升级会员", path: "/pricing" }],
    jsonLd: (context) => [webPageNode(context)],
  },
  {
    name: "terms",
    path: "/terms",
    title: "使用条款",
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
