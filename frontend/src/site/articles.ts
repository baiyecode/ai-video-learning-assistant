/**
 * Article content model: strict frontmatter parsing, validation and the
 * published-only collection. Pure and DOM-free so the client bundle, the SSR
 * prerender and the tests share exactly one implementation.
 *
 * A new Markdown file in ``frontend/content/articles`` is the only thing needed
 * to publish an Article; this module is where bad content fails the build.
 */
import { SITE_NAME } from "@/site/seo";

export const AUTHOR_NAME = "AI 视频学习助手团队";
export const SLUG_PATTERN = /^[a-z0-9]+(-[a-z0-9]+)*$/;
export const DESCRIPTION_MIN_LENGTH = 70;
export const DESCRIPTION_MAX_LENGTH = 160;
export const BODY_MIN_CHARACTERS = 500;
export const READING_CHARACTERS_PER_MINUTE = 400;
export const MAX_DOCUMENT_TITLE_LENGTH = 60;

/** File name with extension, used verbatim in build failures. */
export interface ArticleSource {
  fileName: string;
  source: string;
}

export interface Article {
  slug: string;
  fileName: string;
  title: string;
  description: string;
  /** ``YYYY-MM-DD`` from frontmatter (the only source of dates). */
  published: string;
  updated?: string;
  tags: string[];
  draft: boolean;
  body: string;
  /** Non-whitespace characters in the body, used for reading time. */
  bodyCharacters: number;
  readingMinutes: number;
  author: string;
}

export interface ArticleCollection {
  /** Published Articles, newest first. The only set consumers may index. */
  published: Article[];
  drafts: Article[];
  bySlug: Map<string, Article>;
}

export interface ArticleCollectionOptions {
  /** Concrete public paths (``/features``) that in-body links may target. */
  publicRoutes?: readonly string[];
}

export class ArticleContentError extends Error {
  constructor(fileName: string, reason: string) {
    super(`Article ${fileName}: ${reason}`);
    this.name = "ArticleContentError";
  }
}

const REQUIRED_FIELDS = ["title", "description", "published"] as const;
const ALLOWED_FIELDS = new Set([
  "title",
  "description",
  "published",
  "updated",
  "tags",
  "draft",
]);

interface Frontmatter {
  fields: Map<string, string>;
  body: string;
}

function unquote(value: string): string {
  const trimmed = value.trim();
  if (trimmed.length >= 2) {
    const first = trimmed[0];
    const last = trimmed[trimmed.length - 1];
    if ((first === '"' || first === "'") && first === last) {
      return trimmed.slice(1, -1).trim();
    }
  }
  return trimmed;
}

function splitFrontmatter(fileName: string, source: string): Frontmatter {
  const normalized = source.replace(/^\uFEFF/, "").replace(/\r\n/g, "\n");
  const lines = normalized.split("\n");
  if (lines[0]?.trim() !== "---") {
    throw new ArticleContentError(fileName, 'missing frontmatter block (expected a leading "---" line)');
  }
  const end = lines.findIndex((line, index) => index > 0 && line.trim() === "---");
  if (end === -1) {
    throw new ArticleContentError(fileName, 'unterminated frontmatter block (expected a closing "---" line)');
  }

  const fields = new Map<string, string>();
  for (let index = 1; index < end; index += 1) {
    const line = lines[index];
    if (!line.trim()) continue;
    if (/^\s/.test(line)) {
      throw new ArticleContentError(fileName, "frontmatter values must stay on one line");
    }
    const match = /^([A-Za-z][A-Za-z0-9_]*):(?:\s+(.*))?$/.exec(line);
    if (!match) {
      throw new ArticleContentError(fileName, `cannot parse frontmatter line "${line}"`);
    }
    const key = match[1];
    if (!ALLOWED_FIELDS.has(key)) {
      throw new ArticleContentError(fileName, `unknown frontmatter field "${key}"`);
    }
    if (fields.has(key)) {
      throw new ArticleContentError(fileName, `duplicate frontmatter field "${key}"`);
    }
    fields.set(key, (match[2] ?? "").trim());
  }

  return { fields, body: lines.slice(end + 1).join("\n") };
}

function parseDate(fileName: string, field: string, value: string): string {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    throw new ArticleContentError(fileName, `${field} must use YYYY-MM-DD, got "${value}"`);
  }
  const parsed = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== value) {
    throw new ArticleContentError(fileName, `${field} is not a real calendar date: "${value}"`);
  }
  return value;
}

function parseTags(fileName: string, value: string): string[] {
  const match = /^\[(.*)\]$/.exec(value);
  if (!match) {
    throw new ArticleContentError(fileName, 'tags must be an inline list, e.g. "tags: [B站, 字幕]"');
  }
  const raw = match[1].trim();
  if (!raw) return [];
  const tags = raw.split(",").map((tag) => unquote(tag));
  if (tags.some((tag) => !tag)) {
    throw new ArticleContentError(fileName, "tags must not contain empty items");
  }
  return tags;
}

function parseDraft(fileName: string, value: string): boolean {
  if (value === "true") return true;
  if (value === "false") return false;
  throw new ArticleContentError(fileName, `draft must be true or false, got "${value}"`);
}

function countBodyCharacters(body: string): number {
  return body.replace(/\s/gu, "").length;
}

/** External images would make the build depend on the network and can leak. */
function findExternalImage(body: string): string | undefined {
  const sources: string[] = [];
  for (const match of body.matchAll(/!\[[^\]]*\]\(\s*<?([^)\s>]+)/g)) {
    sources.push(match[1]);
  }
  for (const match of body.matchAll(/<img\b[^>]*\bsrc\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))/gi)) {
    sources.push(match[1] ?? match[2] ?? match[3] ?? "");
  }
  return sources.find((src) => /^(?:https?:)?\/\//i.test(src) || /^data:/i.test(src));
}

/**
 * One root-relative link target, split into the parts the site-wide audit needs.
 * ``href`` keeps the original form for error messages; ``path`` is normalized
 * and ``hash`` is the decoded fragment ("" when absent).
 */
export interface InternalLinkRef {
  href: string;
  path: string;
  hash: string;
}

/** Normalize + split a root-relative href; relative/external targets return undefined. */
export function parseInternalHref(raw: string): InternalLinkRef | undefined {
  const href = raw.trim();
  if (!href.startsWith("/") || href.startsWith("//")) return undefined;
  const hashIndex = href.indexOf("#");
  const beforeHash = hashIndex === -1 ? href : href.slice(0, hashIndex);
  const rawHash = hashIndex === -1 ? "" : href.slice(hashIndex + 1);
  const pathOnly = beforeHash.split("?")[0];
  if (!pathOnly) return undefined;
  return { href, path: normalizeRoute(pathOnly), hash: decodeHash(rawHash) };
}

function decodeHash(hash: string): string {
  if (!hash) return "";
  try {
    return decodeURIComponent(hash);
  } catch {
    return hash;
  }
}

/**
 * Root-relative link targets in a Markdown body (links and ``href`` attributes),
 * with path and anchor preserved. Exported so the site-wide audit (#36) reuses
 * this parser instead of growing a second one.
 */
export function extractInternalLinkRefs(markdown: string): InternalLinkRef[] {
  const targets = new Map<string, InternalLinkRef>();
  const add = (raw: string): void => {
    const ref = parseInternalHref(raw);
    if (ref && !targets.has(ref.href)) targets.set(ref.href, ref);
  };
  for (const match of markdown.matchAll(/\]\(\s*<?([^)\s>]+)/g)) add(match[1]);
  for (const match of markdown.matchAll(/\bhref\s*=\s*(?:"([^"]*)"|'([^']*)')/gi)) {
    add(match[1] ?? match[2] ?? "");
  }
  return [...targets.values()];
}

export function extractInternalLinks(markdown: string): string[] {
  return [...new Set(extractInternalLinkRefs(markdown).map((ref) => ref.path))];
}

function normalizeRoute(route: string): string {
  if (route === "/") return route;
  return route.replace(/\/+$/, "");
}

/**
 * Validate every root-relative link in a published Article against the pages
 * that actually exist. #36 reuses this for links outside articles.
 */
export function validateArticleInternalLinks(
  article: Article,
  publicRoutes: Iterable<string>,
): void {
  const known = new Set([...publicRoutes].map(normalizeRoute));
  for (const target of extractInternalLinks(article.body)) {
    if (!known.has(target)) {
      throw new ArticleContentError(
        article.fileName,
        `internal link "${target}" targets a page that does not exist`,
      );
    }
  }
}

/** Parse one file. Throws ``ArticleContentError`` naming the file and reason. */
export function parseArticle(fileName: string, source: string): Article {
  const slugMatch = /^([a-z0-9-]+)\.md$/.exec(fileName);
  const slug = slugMatch?.[1] ?? fileName.replace(/\.md$/i, "");
  if (!slugMatch || !SLUG_PATTERN.test(slug)) {
    throw new ArticleContentError(
      fileName,
      'file name must be a slug of lowercase ASCII letters, digits and single hyphens (e.g. "bilibili-subtitle-download.md")',
    );
  }

  const { fields, body } = splitFrontmatter(fileName, source);

  for (const field of REQUIRED_FIELDS) {
    if (!fields.get(field)?.trim()) {
      throw new ArticleContentError(fileName, `missing required frontmatter field "${field}"`);
    }
  }

  const title = unquote(fields.get("title") ?? "");
  const description = unquote(fields.get("description") ?? "");
  const published = parseDate(fileName, "published", unquote(fields.get("published") ?? ""));

  const updatedRaw = fields.get("updated");
  const updated = updatedRaw ? parseDate(fileName, "updated", unquote(updatedRaw)) : undefined;
  if (updated && updated < published) {
    throw new ArticleContentError(fileName, `updated (${updated}) must not be earlier than published (${published})`);
  }

  const tagsRaw = fields.get("tags");
  const tags = tagsRaw ? parseTags(fileName, tagsRaw) : [];
  const draftRaw = fields.get("draft");
  const draft = draftRaw ? parseDraft(fileName, draftRaw) : false;

  const titleLength = `${title} · ${SITE_NAME}`.length;
  if (titleLength > MAX_DOCUMENT_TITLE_LENGTH) {
    throw new ArticleContentError(
      fileName,
      `title is too long: ${titleLength} characters including the site suffix (max ${MAX_DOCUMENT_TITLE_LENGTH})`,
    );
  }

  if (description.length < DESCRIPTION_MIN_LENGTH || description.length > DESCRIPTION_MAX_LENGTH) {
    throw new ArticleContentError(
      fileName,
      `description is ${description.length} characters (expected ${DESCRIPTION_MIN_LENGTH}-${DESCRIPTION_MAX_LENGTH})`,
    );
  }

  const trimmedBody = body.trim();
  const bodyCharacters = countBodyCharacters(trimmedBody);
  if (bodyCharacters < BODY_MIN_CHARACTERS) {
    throw new ArticleContentError(
      fileName,
      `body has ${bodyCharacters} non-whitespace characters (expected at least ${BODY_MIN_CHARACTERS})`,
    );
  }

  const externalImage = findExternalImage(trimmedBody);
  if (externalImage) {
    throw new ArticleContentError(
      fileName,
      `external image "${externalImage}" is not allowed; article images must be same-site or omitted`,
    );
  }

  if (/^#\s/m.test(trimmedBody)) {
    throw new ArticleContentError(
      fileName,
      "body must not contain an H1: the page title is the only H1, use ## for sections",
    );
  }

  return {
    slug,
    fileName,
    title,
    description,
    published,
    updated,
    tags,
    draft,
    body: trimmedBody,
    bodyCharacters,
    readingMinutes: Math.max(1, Math.ceil(bodyCharacters / READING_CHARACTERS_PER_MINUTE)),
    author: AUTHOR_NAME,
  };
}

function assertUnique(
  seen: Map<string, string>,
  value: string,
  fileName: string,
  field: "slug" | "title" | "description",
): void {
  const previous = seen.get(value);
  if (previous) {
    throw new ArticleContentError(fileName, `duplicate ${field} "${value}" (already used by ${previous})`);
  }
  seen.set(value, fileName);
}

/** Shared tags first, then newest; never the current Article. */
export function relatedArticles(
  article: Article,
  collection: ArticleCollection,
  limit = 3,
): Article[] {
  const tags = new Set(article.tags);
  return collection.published
    .filter((other) => other.slug !== article.slug)
    .map((other) => ({
      article: other,
      shared: other.tags.filter((tag) => tags.has(tag)).length,
    }))
    .sort(
      (left, right) =>
        right.shared - left.shared ||
        right.article.published.localeCompare(left.article.published) ||
        left.article.slug.localeCompare(right.article.slug),
    )
    .slice(0, limit)
    .map((entry) => entry.article);
}

/** Parse, cross-validate and split a source set into published Articles + drafts. */
export function buildArticleCollection(
  sources: readonly ArticleSource[],
  options: ArticleCollectionOptions = {},
): ArticleCollection {
  const articles = sources.map((source) => parseArticle(source.fileName, source.source));

  const slugs = new Map<string, string>();
  const titles = new Map<string, string>();
  const descriptions = new Map<string, string>();
  for (const article of articles) {
    assertUnique(slugs, article.slug, article.fileName, "slug");
    assertUnique(titles, article.title, article.fileName, "title");
    assertUnique(descriptions, article.description, article.fileName, "description");
  }

  const published = articles
    .filter((article) => !article.draft)
    .sort(
      (left, right) =>
        right.published.localeCompare(left.published) || left.slug.localeCompare(right.slug),
    );
  const drafts = articles
    .filter((article) => article.draft)
    .sort((left, right) => left.slug.localeCompare(right.slug));

  const knownRoutes = new Set(
    [...(options.publicRoutes ?? []), "/articles", ...published.map((article) => `/articles/${article.slug}`)].map(
      normalizeRoute,
    ),
  );
  for (const article of published) {
    validateArticleInternalLinks(article, knownRoutes);
  }

  return {
    published,
    drafts,
    bySlug: new Map(published.map((article) => [article.slug, article])),
  };
}
