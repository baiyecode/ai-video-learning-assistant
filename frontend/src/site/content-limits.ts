/**
 * Content limits shared by the Article parser (``articles.ts``) and the page
 * descriptor validator (``seo.ts``). Keeping the numbers and the frontmatter
 * date rules here means an Article cannot pass the parser while its generated
 * descriptor fails the registry check (or vice versa) because of a drifted
 * magic number or date regex.
 */

/** Full document title including the `` · AI 视频学习助手`` suffix. */
export const MAX_DOCUMENT_TITLE_LENGTH = 60;
export const DESCRIPTION_MIN_LENGTH = 70;
export const DESCRIPTION_MAX_LENGTH = 160;

/** ``YYYY-MM-DD`` frontmatter date; the only date format the site accepts. */
export const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

export interface ArticleDateIssue {
  field: "published" | "updated";
  /** Human-readable reason, appended after the field name by the caller. */
  reason: string;
}

/**
 * Validate the frontmatter dates and their order. Returns the first problem so
 * each caller can raise its own error type (file-based or route-based), or
 * ``undefined`` when the pair is valid.
 */
export function reviewArticleDates(
  published: string,
  updated?: string,
): ArticleDateIssue | undefined {
  for (const [field, value] of [
    ["published", published],
    ["updated", updated],
  ] as const) {
    if (value === undefined) continue;
    if (!DATE_PATTERN.test(value)) {
      return { field, reason: "must use YYYY-MM-DD" };
    }
    const parsed = new Date(`${value}T00:00:00Z`);
    if (Number.isNaN(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== value) {
      return { field, reason: "is not a real calendar date" };
    }
  }
  if (updated !== undefined && updated < published) {
    return { field: "updated", reason: "must not be earlier than published" };
  }
  return undefined;
}
