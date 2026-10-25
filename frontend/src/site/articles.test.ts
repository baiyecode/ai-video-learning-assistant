/**
 * The content seam: frontmatter parsing and every validation rule run on plain
 * strings, so a broken article fails with its file name instead of a blank page.
 */
import { describe, expect, it } from "vitest";

import {
  AUTHOR_NAME,
  ArticleContentError,
  buildArticleCollection,
  parseArticle,
  relatedArticles,
  type ArticleSource,
} from "@/site/articles";

const BODY = "这是一段用于测试的文章正文，用来确认字数统计与阅读时间估算。".repeat(30);

const DESCRIPTION =
  "这是一段用于测试的文章描述，需要覆盖七十到一百六十个字符的长度要求，因此这里多写一些具体内容，确保描述足够详细，既能通过校验，也能清楚说明这篇文章要解决的问题和适用场景。";

function uniqueDescription(label: string): string {
  return `${label}：${DESCRIPTION}`.slice(0, 160);
}

function validSource(overrides: Record<string, string> = {}, body = BODY): string {
  const fields: Record<string, string> = {
    title: "测试文章标题",
    description: DESCRIPTION,
    published: "2026-10-25",
    ...overrides,
  };
  const frontmatter = Object.entries(fields)
    .filter(([, value]) => value !== "")
    .map(([key, value]) => `${key}: ${value}`)
    .join("\n");
  return `---\n${frontmatter}\n---\n\n${body}\n`;
}

function expectFailure(fileName: string, source: string, reason: RegExp): void {
  try {
    parseArticle(fileName, source);
  } catch (error) {
    expect(error).toBeInstanceOf(ArticleContentError);
    expect((error as Error).message).toContain(fileName);
    expect((error as Error).message).toMatch(reason);
    return;
  }
  throw new Error(`expected ${fileName} to be rejected`);
}

describe("parseArticle", () => {
  it("parses required and optional frontmatter plus the body", () => {
    const article = parseArticle(
      "hello-world.md",
      validSource({
        title: "测试文章标题",
        updated: "2026-10-26",
        tags: "[B站, 字幕]",
        draft: "false",
      }),
    );

    expect(article.slug).toBe("hello-world");
    expect(article.fileName).toBe("hello-world.md");
    expect(article.title).toBe("测试文章标题");
    expect(article.description).toBe(DESCRIPTION);
    expect(article.published).toBe("2026-10-25");
    expect(article.updated).toBe("2026-10-26");
    expect(article.tags).toEqual(["B站", "字幕"]);
    expect(article.draft).toBe(false);
    expect(article.body).toContain("用于测试的文章正文");
    expect(article.author).toBe(AUTHOR_NAME);
    expect(article.readingMinutes).toBeGreaterThanOrEqual(1);
  });

  it("rejects a missing title, description or published date", () => {
    expectFailure("no-title.md", validSource({ title: "" }), /title/);
    expectFailure("no-description.md", validSource({ description: "" }), /description/);
    expectFailure("no-published.md", validSource({ published: "" }), /published/);
  });

  it("rejects malformed or impossible dates and updated before published", () => {
    expectFailure("bad-date.md", validSource({ published: "2026/10/25" }), /published/);
    expectFailure("bad-date.md", validSource({ published: "2026-02-30" }), /published/);
    expectFailure("bad-updated.md", validSource({ updated: "2026-13-01" }), /updated/);
    expectFailure(
      "earlier-update.md",
      validSource({ updated: "2026-10-24" }),
      /updated.*published/,
    );
  });

  it("rejects a file name that is not a valid slug", () => {
    expectFailure("Bad Slug.md", validSource(), /slug/);
    expectFailure("under_score.md", validSource(), /slug/);
    expectFailure("-leading.md", validSource(), /slug/);
  });

  it("rejects descriptions outside 70-160 characters", () => {
    expectFailure("short-description.md", validSource({ description: "太短" }), /description/);
    expectFailure(
      "long-description.md",
      validSource({ description: "长".repeat(161) }),
      /description/,
    );
  });

  it("rejects a body under 500 non-whitespace characters", () => {
    expectFailure("short-body.md", validSource({}, "太短的正文"), /body/);
  });

  it("rejects external images in markdown and raw HTML", () => {
    expectFailure(
      "external-image.md",
      validSource({}, `${BODY}\n\n![截图](https://cdn.example.com/a.png)`),
      /image/,
    );
    expectFailure(
      "external-image.md",
      validSource({}, `${BODY}\n\n<img src="//cdn.example.com/b.png" alt="">`),
      /image/,
    );
  });

  it("rejects unknown fields and invalid optional values", () => {
    expectFailure("unknown-field.md", validSource({ author: "某人" }), /author/);
    expectFailure("bad-draft.md", validSource({ draft: "yes" }), /draft/);
    expectFailure("bad-tags.md", validSource({ tags: "B站, 字幕" }), /tags/);
  });

  it("rejects an H1 in the body because the page title is the only H1", () => {
    expectFailure(
      "second-h1.md",
      validSource({}, `${BODY}\n\n# 第二个标题\n`),
      /H1/,
    );
  });

  it("rejects a missing or unterminated frontmatter block", () => {
    expectFailure("no-frontmatter.md", BODY, /frontmatter/);
    expectFailure("open-frontmatter.md", `---\ntitle: 标题\n`, /frontmatter/);
  });
});

describe("buildArticleCollection", () => {
  const sources: ArticleSource[] = [
    {
      fileName: "older-post.md",
      source: validSource({
        title: "较早的文章",
        description: uniqueDescription("较早的文章"),
        published: "2026-10-01",
      }),
    },
    {
      fileName: "newer-post.md",
      source: validSource({
        title: "较新的文章",
        description: uniqueDescription("较新的文章"),
        published: "2026-10-20",
        tags: "[B站, 字幕]",
      }),
    },
    {
      fileName: "draft-post.md",
      source: validSource({
        title: "草稿文章",
        description: uniqueDescription("草稿文章"),
        draft: "true",
      }),
    },
  ];

  it("sorts published articles newest first and keeps drafts separate", () => {
    const collection = buildArticleCollection(sources);

    expect(collection.published.map((article) => article.slug)).toEqual([
      "newer-post",
      "older-post",
    ]);
    expect(collection.drafts.map((article) => article.slug)).toEqual(["draft-post"]);
    expect(collection.bySlug.has("draft-post")).toBe(false);
  });

  it("rejects duplicate titles, descriptions and slugs across the collection", () => {
    expect(() =>
      buildArticleCollection([
        sources[0],
        {
          fileName: "same-title.md",
          source: validSource({ title: "较早的文章", published: "2026-10-02" }),
        },
      ]),
    ).toThrow(/same-title\.md.*title/);

    expect(() =>
      buildArticleCollection([
        sources[0],
        {
          fileName: "same-description.md",
          source: validSource({
            title: "另一篇",
            description: uniqueDescription("较早的文章"),
            published: "2026-10-02",
          }),
        },
      ]),
    ).toThrow(/same-description\.md.*description/);

    expect(() => buildArticleCollection([sources[0], { ...sources[0] }])).toThrow(
      /older-post\.md.*slug/,
    );
  });

  it("accepts internal links to public routes and published articles", () => {
    const collection = buildArticleCollection(
      [
        {
          fileName: "linked-post.md",
          source: validSource(
            { title: "带链接的文章", description: uniqueDescription("带链接的文章") },
            `${BODY}\n\n[功能页](/features) 与 [另一篇](/articles/older-post)\n`,
          ),
        },
        sources[0],
      ],
      { publicRoutes: ["/", "/features"] },
    );

    expect(collection.published[0].slug).toBe("linked-post");
  });

  it("fails with the file name and target when an internal link is unknown", () => {
    expect(() =>
      buildArticleCollection(
        [
          {
            fileName: "broken-link.md",
            source: validSource(
              { title: "坏链接文章", description: uniqueDescription("坏链接文章") },
              `${BODY}\n\n[缺失页](/missing-page)\n`,
            ),
          },
        ],
        { publicRoutes: ["/", "/features"] },
      ),
    ).toThrow(/broken-link\.md.*\/missing-page/);
  });

  it("fails when a link points at a draft article", () => {
    expect(() =>
      buildArticleCollection([
        {
          fileName: "links-draft.md",
          source: validSource(
            { title: "指向草稿的文章", description: uniqueDescription("指向草稿的文章") },
            `${BODY}\n\n[草稿](/articles/draft-post)\n`,
          ),
        },
        sources[2],
      ]),
    ).toThrow(/links-draft\.md.*\/articles\/draft-post/);
  });
});

describe("relatedArticles", () => {
  it("prefers shared tags, then newest, and never returns the current article", () => {
    const collection = buildArticleCollection([
      {
        fileName: "current.md",
        source: validSource({
          title: "当前文章",
          description: uniqueDescription("当前文章"),
          published: "2026-10-10",
          tags: "[B站, 字幕]",
        }),
      },
      {
        fileName: "one-shared.md",
        source: validSource({
          title: "一个共同标签",
          description: uniqueDescription("一个共同标签"),
          published: "2026-10-01",
          tags: "[B站]",
        }),
      },
      {
        fileName: "two-shared.md",
        source: validSource({
          title: "两个共同标签",
          description: uniqueDescription("两个共同标签"),
          published: "2026-10-05",
          tags: "[B站, 字幕]",
        }),
      },
      {
        fileName: "no-shared.md",
        source: validSource({
          title: "没有共同标签",
          description: uniqueDescription("没有共同标签"),
          published: "2026-10-20",
          tags: "[YouTube]",
        }),
      },
    ]);

    const current = collection.bySlug.get("current");
    if (!current) throw new Error("fixture missing");

    expect(relatedArticles(current, collection).map((article) => article.slug)).toEqual([
      "two-shared",
      "one-shared",
      "no-shared",
    ]);
  });
});
