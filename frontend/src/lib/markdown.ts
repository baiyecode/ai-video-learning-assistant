/** Markdown → sanitized HTML. Every render path goes through DOMPurify (XSS). */

import DOMPurify from "dompurify";
import { marked } from "marked";

marked.setOptions({ gfm: true, breaks: true });

export function renderMarkdown(source: string): string {
  if (!source.trim()) return "";
  const html = marked.parse(source) as string;
  return DOMPurify.sanitize(html, { USE_PROFILES: { html: true } });
}
