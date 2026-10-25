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
  return sanitizeHtml(html);
}

let linkHardeningInstalled = false;

/**
 * External links opened from rendered content must not hand the opener over to
 * the target page. Internal links keep their behaviour; the marker attribute is
 * only added when the href leaves the site.
 */
function installLinkHardening(): void {
  if (linkHardeningInstalled) return;
  linkHardeningInstalled = true;
  DOMPurify.addHook("afterSanitizeAttributes", (node) => {
    if (node.tagName === "A") {
      const href = node.getAttribute("href") ?? "";
      if (/^(?:https?:)?\/\//i.test(href)) {
        node.setAttribute("rel", "noopener noreferrer");
      }
    }
  });
}

/** Sanitize already-rendered HTML with the one project-wide policy. */
export function sanitizeHtml(html: string): string {
  installLinkHardening();
  return DOMPurify.sanitize(html, {
    USE_PROFILES: { html: true },
    FORBID_TAGS: FORBIDDEN_TAGS,
  });
}
