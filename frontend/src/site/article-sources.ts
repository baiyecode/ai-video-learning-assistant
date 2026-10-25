/**
 * The one place that reads the repo-tracked Markdown collection. Vite inlines
 * the raw strings for the client build, the SSR build and vitest, so the SPA,
 * the prerenderer and the tests see the same Articles.
 */
import { inject, type InjectionKey } from "vue";

import { buildArticleCollection, type ArticleCollection, type ArticleSource } from "@/site/articles";
import { publicDescriptors } from "@/site/seo";

const rawSources = import.meta.glob("../../content/articles/*.md", {
  eager: true,
  query: "?raw",
  import: "default",
}) as Record<string, string>;

/** Stable order keeps validation errors and the TOC reproducible. */
export const defaultArticleSources: ArticleSource[] = Object.keys(rawSources)
  .sort()
  .map((path) => ({
    fileName: path.split("/").pop() ?? path,
    source: rawSources[path] ?? "",
  }));

let cachedCollection: ArticleCollection | undefined;

/** Published-only collection built from the real content directory. */
export function defaultArticleCollection(): ArticleCollection {
  cachedCollection ??= buildArticleCollection(defaultArticleSources, {
    publicRoutes: publicDescriptors().map((descriptor) => descriptor.path),
  });
  return cachedCollection;
}

/** SSR passes the builder's collection down so fixture content renders too. */
export const ARTICLES_KEY: InjectionKey<ArticleCollection> = Symbol("articles");

export function useArticleCollection(): ArticleCollection {
  return inject(ARTICLES_KEY, null) ?? defaultArticleCollection();
}
