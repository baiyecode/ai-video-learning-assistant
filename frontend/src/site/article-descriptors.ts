/**
 * SEO descriptors for the Article collection. Kept separate from ``seo.ts`` so
 * the static marketing registry stays untouched and content-derived pages are
 * appended by the site builder.
 */
import type { Article, ArticleCollection } from "@/site/articles";
import { AUTHOR_NAME } from "@/site/articles";
import { defaultArticleCollection } from "@/site/article-sources";
import {
  DEFAULT_SHARE_IMAGE,
  HOME_BREADCRUMB,
  INDEX_ROBOTS,
  SITE_NAME,
  canonicalUrl,
  descriptorForRoute,
  type JsonLdContext,
  type JsonLdNode,
  type PageDescriptor,
} from "@/site/seo";

export const ARTICLES_LIST_PATH = "/articles";
export const ARTICLES_LIST_DESCRIPTION =
  "AI 视频学习助手文章列表：按发布时间收录 B 站与 YouTube 字幕导出、视频学习笔记与 AI 摘要的实操教程，每篇给出可执行步骤、真实限制与产品边界。";

export function articlePath(slug: string): string {
  return `${ARTICLES_LIST_PATH}/${slug}`;
}

function articleDates(article: Article): { published: string; updated: string } {
  return { published: article.published, updated: article.updated ?? article.published };
}

function blogPostingNode(context: JsonLdContext, article: Article): JsonLdNode {
  const url = context.canonicalUrl;
  const dates = articleDates(article);
  return {
    "@type": "BlogPosting",
    "@id": `${url}#article`,
    url,
    headline: article.title,
    description: article.description,
    datePublished: dates.published,
    dateModified: dates.updated,
    inLanguage: "zh-CN",
    author: { "@type": "Organization", name: AUTHOR_NAME, url: `${context.origin}/` },
    mainEntityOfPage: { "@type": "WebPage", "@id": url },
    image: [context.imageUrl],
    keywords: article.tags.join(", "),
    isPartOf: {
      "@type": "Blog",
      "@id": `${canonicalUrl(context.origin, ARTICLES_LIST_PATH)}#blog`,
      url: canonicalUrl(context.origin, ARTICLES_LIST_PATH),
    },
  };
}

function blogNode(context: JsonLdContext, collection: ArticleCollection): JsonLdNode {
  return {
    "@type": "Blog",
    "@id": `${context.canonicalUrl}#blog`,
    url: context.canonicalUrl,
    name: `${SITE_NAME}文章`,
    description: ARTICLES_LIST_DESCRIPTION,
    inLanguage: "zh-CN",
    publisher: { "@type": "Organization", "@id": `${context.origin}/#organization` },
    blogPost: collection.published.map((article) => {
      const url = canonicalUrl(context.origin, articlePath(article.slug));
      const dates = articleDates(article);
      return {
        "@type": "BlogPosting",
        "@id": `${url}#article`,
        url,
        headline: article.title,
        description: article.description,
        datePublished: dates.published,
        dateModified: dates.updated,
      };
    }),
  };
}

export function articlesListDescriptor(collection: ArticleCollection): PageDescriptor {
  return {
    name: "articles",
    path: ARTICLES_LIST_PATH,
    title: "文章",
    description: ARTICLES_LIST_DESCRIPTION,
    robots: INDEX_ROBOTS,
    ogType: "website",
    image: DEFAULT_SHARE_IMAGE,
    breadcrumbs: [
      HOME_BREADCRUMB,
      { name: "文章", path: ARTICLES_LIST_PATH },
    ],
    jsonLd: (context) => [blogNode(context, collection)],
  };
}

export function articleDescriptor(article: Article): PageDescriptor {
  const dates = articleDates(article);
  return {
    // Names must stay unique within the registry; the router resolves the
    // per-slug descriptor explicitly instead of through the route name.
    name: `article:${article.slug}`,
    path: articlePath(article.slug),
    title: article.title,
    description: article.description,
    robots: INDEX_ROBOTS,
    ogType: "article",
    image: DEFAULT_SHARE_IMAGE,
    imageAlt: article.title,
    article: { ...dates, tags: article.tags },
    breadcrumbs: [
      HOME_BREADCRUMB,
      { name: "文章", path: ARTICLES_LIST_PATH },
      { name: article.title, path: articlePath(article.slug) },
    ],
    jsonLd: (context) => [blogPostingNode(context, article)],
  };
}

/** The list page first, then one descriptor per published Article. */
export function articleDescriptors(collection: ArticleCollection): PageDescriptor[] {
  return [
    articlesListDescriptor(collection),
    ...collection.published.map((article) => articleDescriptor(article)),
  ];
}

/** Runtime lookup for ``/articles/:slug``; unknown slugs get the noindex page. */
export function descriptorForArticleSlug(
  slug: string,
  collection: ArticleCollection = defaultArticleCollection(),
): PageDescriptor {
  const article = collection.bySlug.get(slug);
  return article ? articleDescriptor(article) : descriptorForRoute(undefined);
}
