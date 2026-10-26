/**
 * Article content model: strict frontmatter parsing, validation and the
 * published-only collection. Pure and DOM-free so the client bundle, the SSR
 * prerender and the tests share exactly one implementation.
 *
 * A new Markdown file in ``frontend/content/articles`` is the only thing needed
 * to publish an Article; this module is where bad content fails the build.
 *
 * Money and Quota claims are written as build-time placeholders
 * (``{{MONTHLY_PRICE_USD}}`` / ``{{DAILY_FREE_QUOTA}}``) and resolved here, in the
 * one place the frontmatter title/description and the body pass through, so a
 * repricing deploy moves the Articles with the rest of the site. The description
 * length rule is checked after interpolation, on the text a crawler actually reads.
 * Frontmatter tags are literal labels: a placeholder there fails the build instead
 * of leaking its raw token into ``article:tag``.
 */
import { DAILY_FREE_ANALYSIS_LIMIT, PRICE_HEADLINE } from "@/lib/billing";
import {
  DESCRIPTION_MAX_LENGTH,
  DESCRIPTION_MIN_LENGTH,
  MAX_DOCUMENT_TITLE_LENGTH,
  reviewArticleDates,
} from "@/site/content-limits";
import { SITE_NAME } from "@/site/seo";

export const AUTHOR_NAME = "AI 视频学习助手团队";
export const SLUG_PATTERN = /^[a-z0-9]+(-[a-z0-9]+)*$/;
export const BODY_MIN_CHARACTERS = 500;
export const READING_CHARACTERS_PER_MINUTE = 400;

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

/**
 * The two build-time placeholders an Article source may use for a money or Quota
 * claim, with their values taken from the single ``VITE_`` mirror chain (issue #45):
 * ``PRICE_HEADLINE`` is already the ``$X.XX/月`` form and the Quota mirror refuses a
 * fractional or junk deploy arg, so an Article can never render ``$NaN/月``.
 * Reading them here keeps the interpolation pure — no env access, no DOM, one
 * implementation shared by the client bundle, the prerender and the tests.
 */
const PLACEHOLDER_VALUES = new Map<string, string>([
  ["MONTHLY_PRICE_USD", PRICE_HEADLINE],
  ["DAILY_FREE_QUOTA", String(DAILY_FREE_ANALYSIS_LIMIT)],
]);

const ALLOWED_PLACEHOLDER_HINT =
  "the only allowed placeholders are {{MONTHLY_PRICE_USD}} and {{DAILY_FREE_QUOTA}}";

/** A well-formed ``{{NAME}}`` token: no nesting, no stray braces inside. */
const PLACEHOLDER_PATTERN = /\{\{([^{}]*)\}\}/g;

/**
 * An unclosed ``{{`` left after resolution, reported up to the first space or brace
 * so a build log stays readable. A lone ``}}`` is ordinary text — Markdown prose and
 * code fences may contain one — and deliberately stays legal.
 */
const RESIDUAL_PLACEHOLDER_PATTERN = /\{\{[^\s{}]*/;

/** The two known tokens, blanked out before the literal-claim guard runs. */
const KNOWN_PLACEHOLDER_TOKEN_PATTERN = /\{\{(?:MONTHLY_PRICE_USD|DAILY_FREE_QUOTA)\}\}/g;

/**
 * A hand-written monthly-price claim in the source: a ``$``/``＄`` followed by
 * digits (thousands separators allowed) and a monthly suffix (``/月``, ``／月``,
 * ``/mo``, ``/month`` or ``每月``), tolerating spaces and full-width digits.
 * Interpolated placeholders are masked out before this runs, so only un-templated
 * literals are caught.
 */
const LITERAL_PRICE_PATTERN =
  /[＄$]\s*[\d０-９][\d０-９.,，]*\s*(?:[\/／]\s*(?:月|mo(?:nth)?\b)|每月)/u;

/**
 * A hand-written daily-quota claim in the source: a daily prefix (``每日``,
 * ``每天``, ``自然日`` or ``一天``), an optional qualifier, then a count (Arabic or
 * Chinese numerals) and ``次``, any spacing. The prefix is part of the pattern on
 * purpose — ``消耗 1 次`` or ``1 次 Quota`` describe a single consumption unit, not
 * the daily allowance, and stay legal.
 */
const LITERAL_QUOTA_PATTERN =
  /(?:每日|每天|自然日|一天)\s*(?:最多|至少|可|上限为?)?\s*(?:[\d０-９]+|[零一二三四五六七八九十百千万两]+)\s*次/u;

/**
 * The strict literal-claim guard (issue #45): refuse a field whose SOURCE —
 * with the known placeholder tokens masked out — still spells a money or quota
 * claim by hand. Checking the masked source instead of the interpolated text is
 * what makes the two rules mutually clear: the resolved ``$4.99/月`` of a legal
 * placeholder never trips it, while an Article mixing placeholders and
 * hand-written numbers fails naming the file and the offending snippet.
 * A bare ``数字 次`` without a daily prefix is not a Quota claim (``消耗 1 次``
 * and ``1 次 Quota`` describe one consumption unit and stay legal), so the
 * quota guard keys on the daily prefix, not the count.
 */
function assertNoUntemplatedClaims(fileName: string, raw: string): void {
  const untemplated = raw.replace(KNOWN_PLACEHOLDER_TOKEN_PATTERN, "");

  const literalPrice = LITERAL_PRICE_PATTERN.exec(untemplated)?.[0];
  if (literalPrice) {
    throw new ArticleContentError(
      fileName,
      `literal monthly price "${literalPrice}": money claims must use the placeholder {{MONTHLY_PRICE_USD}}, not hand-written numbers`,
    );
  }

  const literalQuota = LITERAL_QUOTA_PATTERN.exec(untemplated)?.[0];
  if (literalQuota) {
    throw new ArticleContentError(
      fileName,
      `literal daily quota "${literalQuota}": quota claims must use the placeholder {{DAILY_FREE_QUOTA}} (as in "每日 {{DAILY_FREE_QUOTA}} 次"), not hand-written numbers`,
    );
  }
}

/**
 * Resolve every ``{{PLACEHOLDER}}`` in one Article field to its build-time value,
 * then run the literal-claim guard on the same field's source. Ordering is part
 * of the contract: an unknown or unclosed placeholder fails first with its own
 * message (P4-1 behavior), so a field only reaches the guard once its
 * placeholders are valid.
 */
function interpolatePlaceholders(fileName: string, text: string): string {
  const resolved = text.replace(PLACEHOLDER_PATTERN, (token, name: string) => {
    const value = PLACEHOLDER_VALUES.get(name);
    if (value === undefined) {
      throw new ArticleContentError(
        fileName,
        `unknown placeholder "${token}": ${ALLOWED_PLACEHOLDER_HINT}`,
      );
    }
    return value;
  });

  const residual = RESIDUAL_PLACEHOLDER_PATTERN.exec(resolved)?.[0];
  if (residual) {
    throw new ArticleContentError(
      fileName,
      `unclosed placeholder "${residual}": ${ALLOWED_PLACEHOLDER_HINT}`,
    );
  }

  assertNoUntemplatedClaims(fileName, text);
  return resolved;
}

/**
 * Tags are literal labels (``article:tag`` and the visible tag list), so they are
 * never interpolated: placeholder syntax there would leak its raw token. Fail
 * through the same build-time error instead.
 */
function assertNoPlaceholderSyntax(fileName: string, value: string): void {
  if (/\{\{|\}\}/.test(value)) {
    throw new ArticleContentError(
      fileName,
      `tags must not contain placeholders: ${ALLOWED_PLACEHOLDER_HINT}`,
    );
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
 * that actually exist. Path-only, so it also runs in the SPA bundle
 * (``defaultArticleCollection``); the build additionally runs the site-wide
 * ``validateSiteLinks`` audit, which covers anchors and generated HTML too.
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

  const title = interpolatePlaceholders(fileName, unquote(fields.get("title") ?? ""));
  const description = interpolatePlaceholders(
    fileName,
    unquote(fields.get("description") ?? ""),
  );
  const published = unquote(fields.get("published") ?? "");

  const updatedRaw = fields.get("updated");
  const updated = updatedRaw ? unquote(updatedRaw) : undefined;

  const dateIssue = reviewArticleDates(published, updated);
  if (dateIssue) {
    const value = dateIssue.field === "published" ? published : updated;
    throw new ArticleContentError(
      fileName,
      `${dateIssue.field} ${dateIssue.reason}: "${value}"`,
    );
  }

  const tagsRaw = fields.get("tags");
  if (tagsRaw) {
    assertNoPlaceholderSyntax(fileName, tagsRaw);
    assertNoUntemplatedClaims(fileName, tagsRaw);
  }
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

  const trimmedBody = interpolatePlaceholders(fileName, body.trim());
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
