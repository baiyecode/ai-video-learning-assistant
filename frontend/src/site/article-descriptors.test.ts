/**
 * Article SEO descriptors: the same descriptor registry contract as marketing
 * pages, but the dates and tags come from frontmatter and reach the static head
 * and JSON-LD unchanged.
 */
import { describe, expect, it } from "vitest";

import { buildArticleCollection, parseArticle } from "@/site/articles";
import {
  articleDescriptor,
  articleDescriptors,
  articlesListDescriptor,
} from "@/site/article-descriptors";
import { headTags, validateDescriptors } from "@/site/seo";

const ORIGIN = "https://example.com";
const BODY = "这是一段用于测试的文章正文，用来确认结构化数据与 head 中的日期。".repeat(30);
const DESCRIPTION =
  "这是一段用于测试的文章描述，需要覆盖七十到一百六十个字符的长度要求，因此这里多写一些具体内容，确保描述足够详细，既能通过校验，也能清楚说明这篇文章要解决的问题和适用场景。";

interface Overrides {
  description?: string;
  published?: string;
  updated?: string;
  tags?: string;
}

function sourceFor(title: string, overrides: Overrides = {}): string {
  const fields = [
    `title: ${title}`,
    `description: ${overrides.description ?? DESCRIPTION}`,
    `published: ${overrides.published ?? "2026-10-25"}`,
    ...(overrides.updated ? [`updated: ${overrides.updated}`] : []),
    ...(overrides.tags ? [`tags: ${overrides.tags}`] : []),
  ].join("\n");
  return `---\n${fields}\n---\n\n${BODY}\n`;
}

const firstSource = sourceFor("第一篇测试文章", {
  updated: "2026-10-26",
  tags: "[B站, 字幕]",
});
const olderSource = sourceFor("另一篇测试文章", {
  description: `${DESCRIPTION}旧`,
  published: "2026-10-01",
});

const article = parseArticle("first-post.md", firstSource);
const collection = buildArticleCollection([
  { fileName: "first-post.md", source: firstSource },
  { fileName: "older-post.md", source: olderSource },
]);

describe("article descriptors", () => {
  it("derives a unique public descriptor with frontmatter dates and article OG tags", () => {
    const descriptor = articleDescriptor(article);
    const tags = headTags(descriptor, ORIGIN);
    const meta = (key: string, value: string) =>
      tags.find((tag) => tag.tag === "meta" && tag.attrs[key] === value)?.attrs.content;

    expect(descriptor.path).toBe("/articles/first-post");
    expect(descriptor.ogType).toBe("article");
    expect(meta("property", "og:type")).toBe("article");
    expect(meta("property", "article:published_time")).toBe("2026-10-25");
    expect(meta("property", "article:modified_time")).toBe("2026-10-26");
    expect(tags.find((tag) => tag.attrs.rel === "canonical")?.attrs.href).toBe(
      "https://example.com/articles/first-post",
    );
    expect(meta("name", "robots")).toBe("index,follow,max-image-preview:large");
    expect(tags.find((tag) => tag.attrs.name === "twitter:card")?.attrs.content).toBe(
      "summary_large_image",
    );
  });

  it("emits BlogPosting + BreadcrumbList with headline, author, publisher and tags", () => {
    const tags = headTags(articleDescriptor(article), ORIGIN);
    const script = tags.find((tag) => tag.tag === "script");
    const graph = JSON.parse(script?.text ?? "")["@graph"] as Array<Record<string, any>>;
    const posting = graph.find((node) => node["@type"] === "BlogPosting") as Record<string, any>;
    const breadcrumb = graph.find((node) => node["@type"] === "BreadcrumbList") as Record<string, any>;

    expect(posting.headline).toBe("第一篇测试文章");
    expect(posting.description).toBe(DESCRIPTION);
    expect(posting.datePublished).toBe("2026-10-25");
    expect(posting.dateModified).toBe("2026-10-26");
    expect(posting.inLanguage).toBe("zh-CN");
    expect(posting.keywords).toBe("B站, 字幕");
    expect(posting.mainEntityOfPage).toMatchObject({
      "@id": "https://example.com/articles/first-post",
    });
    expect(posting.author).toMatchObject({ "@type": "Organization", name: "AI 视频学习助手团队" });
    expect(posting.publisher).toMatchObject({ "@type": "Organization" });
    expect(posting.image).toEqual(["https://example.com/brand/share-card.png"]);
    expect(breadcrumb.itemListElement).toHaveLength(3);
    expect(breadcrumb.itemListElement[1]).toMatchObject({
      name: "文章",
      item: "https://example.com/articles",
    });
  });

  it("builds a Blog descriptor for the list with published posts only", () => {
    const descriptors = articleDescriptors(collection);
    const tags = headTags(articlesListDescriptor(collection), ORIGIN);
    const graph = JSON.parse(tags.find((tag) => tag.tag === "script")?.text ?? "")["@graph"] as Array<
      Record<string, any>
    >;
    const blog = graph.find((node) => node["@type"] === "Blog");
    if (!blog) throw new Error("Blog node missing");

    expect(descriptors).toHaveLength(3);
    expect(descriptors.map((descriptor) => descriptor.path)).toEqual([
      "/articles",
      "/articles/first-post",
      "/articles/older-post",
    ]);
    expect(blog.blogPost.map((post: { headline: string }) => post.headline)).toEqual([
      "第一篇测试文章",
      "另一篇测试文章",
    ]);
    expect(blog.publisher).toEqual({
      "@type": "Organization",
      "@id": "https://example.com/#organization",
    });
    expect(graph.some((node) => node["@type"] === "BreadcrumbList")).toBe(true);
    validateDescriptors(descriptors);
  });

  it("keeps article titles within the global document-title limit", () => {
    expect(() => validateDescriptors(articleDescriptors(collection))).not.toThrow();
    expect(articleDescriptor(article).title.length).toBeLessThan(48);
  });
});
