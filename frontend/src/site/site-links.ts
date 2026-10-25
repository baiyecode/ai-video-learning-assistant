/**
 * Site-wide internal link audit. Runs after every public page is generated so
 * the anchor set of each page is known, and checks the HTML CTAs/navigation as
 * well as the Article Markdown sources.
 *
 * A link is valid when it targets:
 * - a produced public page,
 * - an allowed private app route (``/login``, ``/account``, ``/analyses``,
 *   ``/analyses/:id``, ``/verify-email``), or
 * - an existing id/anchor on the target page (same-page hashes included).
 *
 * External ``http(s)://``, ``mailto:`` and ``tel:`` links are ignored;
 * ``javascript:`` must never reach the output at all.
 */
import {
  extractInternalLinkRefs,
  parseInternalHref,
  type InternalLinkRef,
} from "@/site/articles";
import { PRIVATE_APP_ROUTES } from "@/site/routes";

export interface GeneratedPage {
  /** Canonical route path, used verbatim in error messages. */
  path: string;
  html: string;
}

export interface MarkdownSource {
  /** Route the Markdown is rendered into (``/articles/<slug>``). */
  path: string;
  source: string;
}

export interface SiteLinkValidationOptions {
  pages: readonly GeneratedPage[];
  /** Published Article bodies; their links follow the same rules. */
  markdown?: readonly MarkdownSource[];
}

/** Private app routes that legitimately appear in navigation/CTAs. */
const ALLOWED_APP_ROUTES = new Set<string>(PRIVATE_APP_ROUTES);
const ANALYSIS_DETAIL_ROUTE = /^\/analyses\/[^/]+$/;

export function isAllowedAppRoute(path: string): boolean {
  return ALLOWED_APP_ROUTES.has(path) || ANALYSIS_DETAIL_ROUTE.test(path);
}

export class SiteLinkError extends Error {
  constructor(source: string, target: string, reason: string) {
    super(`Broken internal link on page ${source}: "${target}" ${reason}`);
    this.name = "SiteLinkError";
  }
}

function unescapeAttribute(value: string): string {
  return value
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">");
}

function decodeFragment(hash: string): string {
  if (!hash) return "";
  try {
    return decodeURIComponent(hash);
  } catch {
    return hash;
  }
}

/** Every ``id`` (and ``<a name>``) value in a generated page. */
export function collectAnchors(html: string): Set<string> {
  const anchors = new Set<string>();
  for (const match of html.matchAll(/\sid\s*=\s*(?:"([^"]*)"|'([^']*)')/gi)) {
    anchors.add(match[1] ?? match[2] ?? "");
  }
  for (const match of html.matchAll(/<a\b[^>]*\sname\s*=\s*(?:"([^"]*)"|'([^']*)')/gi)) {
    anchors.add(match[1] ?? match[2] ?? "");
  }
  anchors.delete("");
  return anchors;
}

/** Hrefs of real ``<a>`` links (assets in ``<link>``/``<script>`` are not links). */
export function collectAnchorHrefs(html: string): string[] {
  const hrefs: string[] = [];
  for (const match of html.matchAll(/<a\b[^>]*?\shref\s*=\s*(?:"([^"]*)"|'([^']*)')/gi)) {
    hrefs.push(unescapeAttribute(match[1] ?? match[2] ?? ""));
  }
  return hrefs;
}

const EXTERNAL_HREF = /^(?:[a-z][a-z0-9+.-]*:|\/\/)/i;

function samePageRef(href: string, pagePath: string): InternalLinkRef | undefined {
  if (!href.startsWith("#")) return undefined;
  return { href, path: pagePath, hash: decodeFragment(href.slice(1)) };
}

export function validateSiteLinks(options: SiteLinkValidationOptions): void {
  const anchorsByPage = new Map<string, Set<string>>();
  for (const page of options.pages) anchorsByPage.set(page.path, collectAnchors(page.html));

  const check = (source: string, ref: InternalLinkRef): void => {
    const target = ref.path;
    if (isAllowedAppRoute(target)) return;
    const anchors = anchorsByPage.get(target);
    if (!anchors) {
      throw new SiteLinkError(source, ref.href, `targets ${target}, which is not a generated page`);
    }
    if (ref.hash && !anchors.has(ref.hash)) {
      throw new SiteLinkError(
        source,
        ref.href,
        `targets ${target}, which has no anchor "#${ref.hash}"`,
      );
    }
  };

  const checkHref = (source: string, raw: string): void => {
    const href = raw.trim();
    if (!href) return;
    if (/^javascript:/i.test(href)) {
      throw new SiteLinkError(source, href, "contains a javascript: URL, which must never appear in output");
    }
    if (EXTERNAL_HREF.test(href)) return;
    const samePage = samePageRef(href, source);
    if (samePage) {
      check(source, samePage);
      return;
    }
    const ref = parseInternalHref(href);
    if (ref) {
      check(source, ref);
      return;
    }
    throw new SiteLinkError(source, href, "is not a root-relative link; use an absolute /path");
  };

  for (const page of options.pages) {
    // The hard security rule: no javascript: URL may survive into any page.
    if (/javascript:/i.test(page.html)) {
      throw new SiteLinkError(
        page.path,
        "javascript:",
        "contains a javascript: URL, which must never appear in output",
      );
    }
    for (const href of collectAnchorHrefs(page.html)) checkHref(page.path, href);
  }

  for (const source of options.markdown ?? []) {
    // Images are not links; strip them before reusing the Markdown link parser.
    const text = source.source.replace(/!\[[^\]]*\]\([^)]*\)/g, "");
    for (const ref of extractInternalLinkRefs(text)) check(source.path, ref);
  }
}
