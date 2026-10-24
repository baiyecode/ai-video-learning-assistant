/** Markdown → sanitized HTML. Every render path goes through DOMPurify (XSS). */

import DOMPurify from "dompurify";
import { marked } from "marked";

marked.setOptions({ gfm: true, breaks: true });

// Model output never needs these: scripts/frames/forms can execute or phish.
const FORBIDDEN_TAGS = [
  "script",
  "style",
  "iframe",
  "object",
  "embed",
  "form",
  "input",
  "button",
  "textarea",
  "select",
  "option",
  "link",
  "meta",
  "base",
];

export function renderMarkdown(source: string): string {
  if (!source.trim()) return "";
  const html = marked.parse(source) as string;
  return DOMPurify.sanitize(html, {
    USE_PROFILES: { html: true },
    FORBID_TAGS: FORBIDDEN_TAGS,
  });
}
