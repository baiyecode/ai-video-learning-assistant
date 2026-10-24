/** Chinese user-facing messages for stable auth error codes. */
import { EMAIL_NOT_VERIFIED_MESSAGE } from "@/lib/uiError";

const AUTH_MESSAGES: Record<string, string> = {
  invalid_credentials: "邮箱或密码不正确",
  email_taken: "该邮箱已注册，请直接登录",
  weak_password: "密码至少需要 8 位",
  invalid_request: "请检查邮箱格式与密码",
  auth_required: "登录状态已失效，请重新登录",
  session_invalid: "登录状态已失效，请重新登录",
  // One gate, one sentence: the email-gate copy lives in uiError (spec ticket #22).
  email_not_verified: EMAIL_NOT_VERIFIED_MESSAGE,
  subscription_not_found: "还没有可管理的订阅，请先完成升级支付",
  too_many_requests: "尝试过于频繁，请稍后再试",
  service_unavailable: "服务暂时不可用，请稍后再试",
  internal_error: "服务器内部错误，请稍后重试",
};

const GENERIC_MESSAGE = "操作失败，请稍后重试";

export function authErrorMessage(code: string | null | undefined): string {
  if (code && AUTH_MESSAGES[code]) return AUTH_MESSAGES[code];
  return GENERIC_MESSAGE;
}

/** Rate-limit envelope fields carried by ``ApiError.details`` on 429. */
interface RateLimitDetails {
  retry_after?: unknown;
  reset_at?: unknown;
}

/**
 * Copy for a refused verification re-send: the backend rate-limits per Account and
 * reports ``retry_after`` seconds plus the ``reset_at`` instant it lifts.
 */
export function verificationResendNotice(details: RateLimitDetails): string {
  const retryAfter =
    typeof details.retry_after === "number" && details.retry_after > 0
      ? Math.ceil(details.retry_after / 60)
      : null;
  const resetAt = typeof details.reset_at === "string" ? details.reset_at : null;
  const day = resetAt ? shanghaiMinute(resetAt) : null;
  if (retryAfter !== null && day) {
    return `发送验证邮件过于频繁，请约 ${retryAfter} 分钟后再试（${day} 后可重试）。`;
  }
  if (retryAfter !== null) {
    return `发送验证邮件过于频繁，请约 ${retryAfter} 分钟后再试。`;
  }
  if (day) return `发送验证邮件过于频繁，${day} 后可重试。`;
  return "发送验证邮件过于频繁，请稍后再试。";
}

/** `2026-01-16T02:15:00+00:00` → `01-16 10:15` in Asia/Shanghai. */
function shanghaiMinute(iso: string): string | null {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  const parts = new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(date);
  const part = (type: Intl.DateTimeFormatPartTypes): string =>
    parts.find((item) => item.type === type)?.value ?? "";
  return `${part("month")}-${part("day")} ${part("hour")}:${part("minute")}`;
}
