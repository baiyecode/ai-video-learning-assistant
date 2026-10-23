/** Pure validation and payload shaping for the Terms page report form. */

export interface ReportReasonOption {
  value: string;
  label: string;
}

/** Must match ``ReportReason`` in ``backend/app/modules/ops/reports.py``. */
export const REPORT_REASONS: readonly ReportReasonOption[] = [
  { value: "copyright", label: "侵犯版权" },
  { value: "drm_bypass", label: "绕过 DRM 或会员权限" },
  { value: "abuse", label: "滥用或恶意使用" },
  { value: "other", label: "其他" },
];

export const REPORT_LIMITS = {
  url: 2048,
  contact: 256,
  details: 2000,
} as const;

export interface ReportFormInput {
  url: string;
  reason: string;
  contact: string;
  details: string;
}

export interface ReportPayload {
  reason: string;
  url?: string;
  contact?: string;
  details?: string;
}

/** Returns a Chinese hint, or ``null`` when the form can be submitted. */
export function validateReport(input: ReportFormInput): string | null {
  if (!REPORT_REASONS.some((reason) => reason.value === input.reason)) {
    return "请选择举报原因";
  }

  const url = input.url.trim();
  if (url.length > REPORT_LIMITS.url) return "举报链接过长";
  if (url && !isHttpUrl(url)) return "举报链接需为 http 或 https 地址";

  if (input.contact.trim().length > REPORT_LIMITS.contact) {
    return `联系方式最多 ${REPORT_LIMITS.contact} 个字符`;
  }
  if (input.details.trim().length > REPORT_LIMITS.details) {
    return `详情最多 ${REPORT_LIMITS.details} 个字符`;
  }
  return null;
}

/** Trimmed API payload; blank optional fields are omitted rather than sent as ``""``. */
export function toReportPayload(input: ReportFormInput): ReportPayload {
  const payload: ReportPayload = { reason: input.reason };
  const url = input.url.trim();
  const contact = input.contact.trim();
  const details = input.details.trim();
  if (url) payload.url = url;
  if (contact) payload.contact = contact;
  if (details) payload.details = details;
  return payload;
}

function isHttpUrl(value: string): boolean {
  try {
    const parsed = new URL(value);
    return (parsed.protocol === "http:" || parsed.protocol === "https:") && parsed.hostname !== "";
  } catch {
    return false;
  }
}
