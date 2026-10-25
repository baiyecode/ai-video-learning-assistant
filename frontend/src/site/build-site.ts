/**
 * Testable site builder (the single artifact seam): takes the build-time origin,
 * the descriptor registry, a route -> {html} renderer, the client-build shell and
 * an output directory, then writes every public page as static HTML.
 *
 * ``scripts/prerender.mjs`` and the unit tests both call this; no head logic is
 * duplicated outside ``site/seo.ts``.
 */
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

import {
  isPublicDescriptor,
  pageDescriptors,
  publicDescriptors,
  renderHeadHtml,
  validateDescriptors,
  type PageDescriptor,
} from "@/site/seo";
import { articleDescriptors, articlePath } from "@/site/article-descriptors";
import {
  buildArticleCollection,
  type ArticleCollection,
  type ArticleSource,
} from "@/site/articles";
import { defaultArticleSources } from "@/site/article-sources";
import { buildDiscoveryArtifacts, writeDiscoveryArtifacts } from "@/site/discovery";
import { validateSiteLinks } from "@/site/site-links";

export interface RenderedRoute {
  html: string;
}

export interface BuildSiteOptions {
  origin: string;
  descriptors?: readonly PageDescriptor[];
  /** Raw Markdown sources; tests inject fixtures, the build uses the repo content. */
  articleSources?: readonly ArticleSource[];
  shellHtml: string;
  outputDir: string;
  renderRoute: (
    path: string,
    articles?: ArticleCollection,
  ) => Promise<RenderedRoute> | RenderedRoute;
}

export interface BuiltPage {
  path: string;
  file: string;
}

export interface BuildSiteResult {
  pages: BuiltPage[];
}

/** ``/`` -> index.html, ``/features`` -> features.html (nginx looks up .html). */
export function outputFileFor(routePath: string): string {
  return routePath === "/" ? "index.html" : `${routePath.replace(/^\//, "")}.html`;
}

/** Inject the descriptor head and the rendered Vue body into the client shell. */
export function composeDocument(
  shellHtml: string,
  descriptor: PageDescriptor,
  origin: string,
  bodyHtml: string,
): string {
  let shell = shellHtml
    .replace(/<title[^>]*>[\s\S]*?<\/title>/i, "")
    .replace(/<meta\s+name=["']description["'][^>]*>\s*/i, "");

  const mount = /<div id="app"[^>]*>\s*<\/div>/i;
  if (!mount.test(shell)) {
    throw new Error("HTML shell is missing an empty #app mount");
  }
  shell = shell.replace(mount, (match) => {
    const open = /<div id="app"[^>]*>/i.exec(match)?.[0] ?? '<div id="app">';
    return `${open}${bodyHtml}</div>`;
  });

  return shell.replace(
    /<\/head>/i,
    () => `    ${renderHeadHtml(descriptor, origin)}\n  </head>`,
  );
}

function countMatches(html: string, pattern: RegExp): number {
  return (html.match(pattern) ?? []).length;
}

/** Fail the build with the route named when the rendered artifact is unusable. */
function assertArtifact(descriptor: PageDescriptor, html: string): void {
  const route = descriptor.path;
  const titles = countMatches(html, /<title[\s>]/gi);
  if (titles !== 1) {
    throw new Error(`Artifact validation failed for route ${route}: expected 1 <title>, found ${titles}`);
  }
  const h1s = countMatches(html, /<h1[\s>]/gi);
  if (h1s !== 1) {
    throw new Error(`Artifact validation failed for route ${route}: expected 1 <h1>, found ${h1s}`);
  }
  if (!/<link[^>]+rel="canonical"/i.test(html)) {
    throw new Error(`Artifact validation failed for route ${route}: missing canonical link`);
  }
}

export async function buildSite(options: BuildSiteOptions): Promise<BuildSiteResult> {
  const staticDescriptors = options.descriptors ?? pageDescriptors;
  const articles = buildArticleCollection(options.articleSources ?? defaultArticleSources, {
    publicRoutes: publicDescriptors(staticDescriptors).map((descriptor) => descriptor.path),
  });
  // Content-derived Article pages join the same registry, so title/description
  // uniqueness and the head contract are validated once for the whole site.
  const descriptors: readonly PageDescriptor[] = [
    ...staticDescriptors,
    ...articleDescriptors(articles),
  ];
  validateDescriptors(descriptors);

  const pages = publicDescriptors(descriptors);
  const seenFiles = new Set<string>();
  for (const descriptor of pages) {
    const file = outputFileFor(descriptor.path);
    if (seenFiles.has(file)) {
      throw new Error(`SEO descriptor for route ${descriptor.path}: duplicate output file ${file}`);
    }
    seenFiles.add(file);
  }

  await mkdir(options.outputDir, { recursive: true });

  const built: BuiltPage[] = [];
  const generated: { path: string; html: string }[] = [];
  for (const descriptor of pages) {
    if (!isPublicDescriptor(descriptor)) continue;

    let rendered: RenderedRoute;
    try {
      rendered = await options.renderRoute(descriptor.path, articles);
    } catch (error) {
      const reason = error instanceof Error ? error.message : String(error);
      throw new Error(`Prerender failed for route ${descriptor.path}: ${reason}`);
    }

    const html = composeDocument(options.shellHtml, descriptor, options.origin, rendered.html);
    assertArtifact(descriptor, html);

    const file = outputFileFor(descriptor.path);
    const filePath = path.join(options.outputDir, file);
    await mkdir(path.dirname(filePath), { recursive: true });
    await writeFile(filePath, html, "utf8");
    built.push({ path: descriptor.path, file });
    generated.push({ path: descriptor.path, html });
  }

  // Anchors are only complete once every page exists, so the site-wide audit
  // runs here: a broken CTA, navigation entry or Article cross-link fails the
  // build instead of shipping a dead internal link.
  validateSiteLinks({
    pages: generated,
    markdown: articles.published.map((article) => ({
      path: articlePath(article.slug),
      source: article.body,
    })),
  });

  // Discovery artifacts derive from the same registry and collection, so the
  // sitemap/llms.txt cannot disagree with the pages that were just written.
  await writeDiscoveryArtifacts(
    options.outputDir,
    buildDiscoveryArtifacts(options.origin, descriptors, articles),
    options.origin,
  );

  return { pages: built };
}
