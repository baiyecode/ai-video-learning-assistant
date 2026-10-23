// @vitest-environment jsdom
/**
 * Markdown rendering is the only place where model/subtitle text becomes HTML.
 * Every injected pattern must be harmless after `renderMarkdown`.
 */
import { describe, expect, it } from "vitest";

import { renderMarkdown } from "@/lib/markdown";

describe("renderMarkdown", () => {
  it("renders ordinary markdown to HTML", () => {
    const html = renderMarkdown("## 标题\n\n- 要点一\n- **要点二**");

    expect(html).toContain("<h2>标题</h2>");
    expect(html).toContain("<li>要点一</li>");
    expect(html).toContain("<strong>要点二</strong>");
  });

  it("strips inline and block script tags", () => {
    const html = renderMarkdown("<script>alert(1)</script>\n\n正文");

    expect(html).not.toMatch(/<script/i);
    expect(html).not.toMatch(/alert\(1\)/);
    expect(html).toContain("正文");
  });

  it("strips event handlers from raw HTML", () => {
    const html = renderMarkdown('<img src="x" onerror="alert(1)">\n\n<p onclick="alert(2)">段落</p>');

    expect(html).not.toMatch(/onerror/i);
    expect(html).not.toMatch(/onclick/i);
    expect(html).toContain("段落");
  });

  it("drops javascript: links but keeps their text", () => {
    const html = renderMarkdown("[点我](javascript:alert(1))");

    expect(html).not.toMatch(/javascript:/i);
    expect(html).toContain("点我");
  });

  it("drops javascript: image sources", () => {
    const html = renderMarkdown("![图片](javascript:alert(1))");

    expect(html).not.toMatch(/javascript:/i);
  });

  it("removes frames and forms that could execute or exfiltrate", () => {
    const html = renderMarkdown(
      '<iframe src="https://evil.example"></iframe><form action="/x"><input name="a"></form>',
    );

    expect(html).not.toMatch(/<iframe/i);
    expect(html).not.toMatch(/<form/i);
  });

  it("keeps safe http(s) links", () => {
    const html = renderMarkdown("[示例](https://example.com/a?b=1)");

    expect(html).toContain('href="https://example.com/a?b=1"');
  });

  it("returns an empty string for blank input", () => {
    expect(renderMarkdown("   ")).toBe("");
  });
});
