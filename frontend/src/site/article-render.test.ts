// @vitest-environment jsdom
/**
 * Article Markdown rendering: deterministic heading anchors for the TOC and the
 * same DOMPurify policy as the rest of the app, with external links hardened.
 */
import { describe, expect, it } from "vitest";

import { renderArticleMarkdown } from "@/site/article-render";

describe("renderArticleMarkdown", () => {
  it("gives every H2/H3 a stable Chinese-friendly anchor and builds the TOC", () => {
    const { html, toc } = renderArticleMarkdown(
      [
        "## B 站字幕怎么下载？",
        "",
        "正文。",
        "",
        "### 一、导出步骤",
        "",
        "#### 更深的标题不进目录",
        "",
        "## B 站字幕怎么下载？",
      ].join("\n"),
    );

    expect(toc).toEqual([
      { id: "b-站字幕怎么下载", text: "B 站字幕怎么下载？", depth: 2 },
      { id: "一-导出步骤", text: "一、导出步骤", depth: 3 },
      { id: "b-站字幕怎么下载-2", text: "B 站字幕怎么下载？", depth: 2 },
    ]);
    expect(html).toContain('<h2 id="b-站字幕怎么下载">');
    expect(html).toContain('<h3 id="一-导出步骤">');
    expect(html).toContain('<h2 id="b-站字幕怎么下载-2">');
    expect(html).not.toContain('id="更深的标题不进目录"');
  });

  it("produces the same anchors on every render", () => {
    const source = "## 同一个标题\n\n正文\n\n## 同一个标题";
    expect(renderArticleMarkdown(source)).toEqual(renderArticleMarkdown(source));
  });

  it("removes scripts, frames, forms and event handlers", () => {
    const { html } = renderArticleMarkdown(
      [
        "## 安全",
        "",
        "<script>alert(1)</script>",
        "",
        '<iframe src="https://evil.example"></iframe>',
        "",
        '<form action="/steal"><input name="a"></form>',
        "",
        '<img src="/local.png" onerror="alert(2)">',
        "",
        "[危险](javascript:alert(3))",
      ].join("\n"),
    );

    expect(html).not.toMatch(/<script/i);
    expect(html).not.toMatch(/<iframe/i);
    expect(html).not.toMatch(/<form/i);
    expect(html).not.toMatch(/onerror/i);
    expect(html).not.toMatch(/javascript:/i);
    expect(html).toContain('id="安全"');
  });

  it("adds noopener noreferrer to external links only", () => {
    const { html } = renderArticleMarkdown(
      "[外部](https://example.com/a) 与 [内部](/features) 与 ![本地图](/local.png)",
    );

    expect(html).toContain('href="https://example.com/a"');
    expect(html).toMatch(/<a[^>]+href="https:\/\/example\.com\/a"[^>]+rel="noopener noreferrer"/);
    expect(html).not.toMatch(/<a[^>]+href="\/features"[^>]+rel=/);
    expect(html).toContain('src="/local.png"');
  });
});
