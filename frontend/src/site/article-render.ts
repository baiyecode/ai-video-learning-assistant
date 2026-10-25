/**
 * Article Markdown rendering: adds deterministic H2/H3 anchors for the table of
 * contents, then runs the shared DOMPurify policy from ``lib/markdown``.
 */
import { Marked } from "marked";

import { sanitizeHtml } from "@/lib/markdown";

export interface TocEntry {
  id: string;
  text: string;
  depth: 2 | 3;
}

export interface RenderedArticleMarkdown {
  html: string;
  toc: TocEntry[];
}

/**
 * Readable, rebuild-stable id: lowercase, letters/numbers kept (Chinese
 * included), everything else collapses to a hyphen. Duplicates get ``-2``, ...
 */
export function headingId(text: string, used: Map<string, number>): string {
  const base =
    text
      .normalize("NFKC")
      .toLowerCase()
      .replace(/[^\p{L}\p{N}]+/gu, "-")
      .replace(/^-+|-+$/g, "") || "section";
  const seen = used.get(base) ?? 0;
  used.set(base, seen + 1);
  return seen === 0 ? base : `${base}-${seen + 1}`;
}

export function renderArticleMarkdown(source: string): RenderedArticleMarkdown {
  const toc: TocEntry[] = [];
  const used = new Map<string, number>();
  const instance = new Marked({ gfm: true, breaks: true });

  instance.use({
    renderer: {
      heading({ tokens, depth }) {
        const text = this.parser.parseInline(tokens, this.parser.textRenderer).trim();
        const inner = this.parser.parseInline(tokens);
        if (depth !== 2 && depth !== 3) return `<h${depth}>${inner}</h${depth}>\n`;
        const id = headingId(text, used);
        toc.push({ id, text, depth });
        return `<h${depth} id="${id}">${inner}</h${depth}>\n`;
      },
    },
  });

  const html = sanitizeHtml(instance.parse(source) as string);
  return { html, toc };
}
