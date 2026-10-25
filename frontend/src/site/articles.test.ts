/**
 * The content seam: frontmatter parsing and every validation rule run on plain
 * strings, so a broken article fails with its file name instead of a blank page.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  AUTHOR_NAME,
  ArticleContentError,
  buildArticleCollection,
  parseArticle,
  relatedArticles,
  type Article,
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

/** The two build-time placeholders an Article source may use (issue #45). */
const PRICE_PLACEHOLDER = "{{MONTHLY_PRICE_USD}}";
const QUOTA_PLACEHOLDER = "{{DAILY_FREE_QUOTA}}";

/**
 * Body plus a description whose interpolated form is 90 characters
 * (``会员 $4.99/月，每日 3 次 Analysis，`` = 27 characters, plus the filler).
 */
const PLACEHOLDER_DESCRIPTION = `会员 ${PRICE_PLACEHOLDER}，每日 ${QUOTA_PLACEHOLDER} 次 Analysis，${"详".repeat(63)}`;
const PLACEHOLDER_BODY = `${BODY}\n\n免费会员每月 ${PRICE_PLACEHOLDER}，免费账号自然日 ${QUOTA_PLACEHOLDER} 次 Analysis。`;

/**
 * Parse with the given ``VITE_`` build args, the same way a repricing deploy does:
 * the module graph is re-evaluated so the mirrors pick the injected values up.
 */
async function parseWithBuildArgs(
  env: Record<string, string>,
  fileName: string,
  source: string,
): Promise<Article> {
  vi.resetModules();
  for (const [key, value] of Object.entries(env)) {
    vi.stubEnv(key as "VITE_ANALYSIS_DAILY_QUOTA", value);
  }
  const fresh = await import("@/site/articles");
  return fresh.parseArticle(fileName, source);
}

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

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

describe("article price placeholder interpolation", () => {
  it("renders the price and free-quota placeholders in the body and description", () => {
    const article = parseArticle(
      "placeholder-defaults.md",
      validSource({ description: PLACEHOLDER_DESCRIPTION }, PLACEHOLDER_BODY),
    );

    expect(article.body).toContain("免费会员每月 $4.99/月");
    expect(article.body).toContain("免费账号自然日 3 次 Analysis");
    expect(article.description).toContain("会员 $4.99/月，每日 3 次 Analysis");
    expect(article.body).not.toContain("{{");
    expect(article.description).not.toContain("{{");
  });

  it("renders the injected build-time price and quota instead of the defaults", async () => {
    const article = await parseWithBuildArgs(
      { VITE_SUBSCRIPTION_MONTHLY_USD: "8.5", VITE_ANALYSIS_DAILY_QUOTA: "7" },
      "repriced.md",
      validSource({ description: PLACEHOLDER_DESCRIPTION }, PLACEHOLDER_BODY),
    );

    expect(article.body).toContain("免费会员每月 $8.50/月");
    expect(article.body).toContain("免费账号自然日 7 次 Analysis");
    expect(article.description).toContain("会员 $8.50/月，每日 7 次 Analysis");
  });

  it("judges the description length on the interpolated text, not on the source", () => {
    // Raw form is 72 characters (would pass a 70-160 pre-check) but interpolates
    // down to 39, so the parser must reject it.
    expectFailure(
      "short-after-interpolation.md",
      validSource({
        description: `会员 ${PRICE_PLACEHOLDER}，每日 ${QUOTA_PLACEHOLDER} 次 Analysis，${"详".repeat(12)}`,
      }),
      /description is 39 characters/,
    );

    // Raw form is 165 characters (a pre-check would reject it) but interpolates
    // down to 132, so the parser must accept it.
    const article = parseArticle(
      "long-before-interpolation.md",
      validSource(
        {
          description: `会员 ${PRICE_PLACEHOLDER}，每日 ${QUOTA_PLACEHOLDER} 次 Analysis，${"详".repeat(105)}`,
        },
        PLACEHOLDER_BODY,
      ),
    );
    expect(article.description.length).toBe(132);
  });

  it("reports an unknown placeholder before any other validation", () => {
    expectFailure(
      "unknown-placeholder.md",
      validSource({}, `${BODY}\n\n会员每月 {{MONTHLY_PRICE}} 即可解锁。`),
      /unknown placeholder "\{\{MONTHLY_PRICE\}\}"/,
    );
  });

  it("rejects an unclosed or leftover placeholder left after resolution", () => {
    expectFailure(
      "unclosed-placeholder.md",
      validSource({}, `${BODY}\n\n会员每月 {{MONTHLY_PRICE_USD 即可解锁。`),
      /unclosed placeholder "\{\{MONTHLY_PRICE_USD"/,
    );
    expectFailure(
      "stray-brace.md",
      validSource({}, `${BODY}\n\n会员每月 4.99/月}} 即可解锁。`),
      /unclosed placeholder "\}\}"/,
    );
    expectFailure(
      "doubled-brace.md",
      validSource(
        { description: `会员 ${PRICE_PLACEHOLDER}，每日 ${QUOTA_PLACEHOLDER} 次 Analysis，${"详".repeat(63)}` },
        `{{{${PRICE_PLACEHOLDER}}}}\n\n${BODY}`,
      ),
      /unclosed placeholder/,
    );
  });

  it("renders the committed defaults for a junk price or a fractional quota", async () => {
    // Mirror fallback semantics (``readBuildEnvNumber``): a fractional Quota and an
    // unparseable price are refused, so an Article never renders ``$NaN/月``.
    const article = await parseWithBuildArgs(
      { VITE_SUBSCRIPTION_MONTHLY_USD: "not-a-number", VITE_ANALYSIS_DAILY_QUOTA: "2.5" },
      "junk-build-args.md",
      validSource({ description: PLACEHOLDER_DESCRIPTION }, PLACEHOLDER_BODY),
    );

    expect(article.body).toContain("免费会员每月 $4.99/月");
    expect(article.body).toContain("免费账号自然日 3 次 Analysis");
    expect(article.body).not.toContain("NaN");
    expect(article.description).toContain("会员 $4.99/月，每日 3 次 Analysis");
  });

  it("interpolates through the collection so every consumer reads the same text", () => {
    const collection = buildArticleCollection([
      {
        fileName: "placeholder-defaults.md",
        source: validSource({ description: PLACEHOLDER_DESCRIPTION }, PLACEHOLDER_BODY),
      },
    ]);

    const article = collection.published[0];
    expect(article.description).toContain("$4.99/月");
    expect(article.body).toContain("自然日 3 次 Analysis");
    expect(collection.drafts).toHaveLength(0);
  });
});

describe("article literal-claim guard", () => {
  it("fails the build on a hand-written monthly price in the body", () => {
    expectFailure(
      "literal-price.md",
      validSource({}, `${BODY}\n\n限时优惠，会员只要 $9.99/月。`),
      /literal monthly price "\$9\.99\/月"/,
    );
  });

  it("fails the build on a hand-written daily quota in every prefix and spacing variant", () => {
    expectFailure(
      "literal-quota-meiri.md",
      validSource({}, `${BODY}\n\n免费用户每日 3 次 Analysis。`),
      /literal daily quota "每日 3 次"/,
    );
    expectFailure(
      "literal-quota-meitian.md",
      validSource({}, `${BODY}\n\n免费用户每天5次 Analysis。`),
      /literal daily quota "每天5次"/,
    );
    expectFailure(
      "literal-quota-ziranri.md",
      validSource({}, `${BODY}\n\n按 Asia/Shanghai 自然日 3    次 重置。`),
      /literal daily quota "自然日 3    次"/,
    );
  });

  it("fails on the literal when an Article mixes placeholders and hand-written numbers", () => {
    expectFailure(
      "mixed-claims.md",
      validSource({}, `${BODY}\n\n现价 ${PRICE_PLACEHOLDER}，限时旧价 $9.99/月。`),
      /literal monthly price "\$9\.99\/月"/,
    );
    expectFailure(
      "mixed-quota.md",
      validSource({}, `${BODY}\n\n免费 每日 ${QUOTA_PLACEHOLDER} 次，加量档 每日 5 次。`),
      /literal daily quota "每日 5 次"/,
    );
  });

  it("resolves placeholders first: an unknown placeholder still fails as a placeholder problem", () => {
    expectFailure(
      "unknown-and-literal.md",
      validSource({}, `${BODY}\n\n会员 {{MONTHLY_PRICE}}，旧价 $9.99/月。`),
      /unknown placeholder "\{\{MONTHLY_PRICE\}\}"/,
    );
    expectFailure(
      "unclosed-and-literal.md",
      validSource({}, `${BODY}\n\n会员 {{MONTHLY_PRICE_USD，旧价 $9.99/月。`),
      /unclosed placeholder/,
    );
  });

  it("guards the frontmatter description and the tags, not only the body", () => {
    expectFailure(
      "literal-in-description.md",
      validSource({
        description: `${DESCRIPTION.slice(0, 100)}会员 $9.99/月，值得一看。`,
      }),
      /literal monthly price "\$9\.99\/月"/,
    );
    expectFailure(
      "literal-in-tags.md",
      validSource({ tags: `[视频总结, 每日 5 次, 字幕]` }),
      /literal daily quota "每日 5 次"/,
    );
  });

  it("keeps a bare 数字 次 legal: it is a consumption unit, not a daily quota claim", () => {
    const article = parseArticle(
      "single-consumption.md",
      validSource(
        {},
        `${BODY}\n\n只要成功生成一次，消耗的都是 1 次 Quota。\n\n| 发起一次新的 Analysis 并成功 | 消耗 1 次 |`,
      ),
    );
    expect(article.body).toContain("消耗 1 次");
  });

  it("does not trip on a correctly templated claim", () => {
    const article = parseArticle(
      "templated-only.md",
      validSource({ description: PLACEHOLDER_DESCRIPTION }, PLACEHOLDER_BODY),
    );
    expect(article.body).toContain("$4.99/月");
    expect(article.body).toContain("自然日 3 次");
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
