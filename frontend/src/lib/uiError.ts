/**
 * The shape every UI error card reads: a machine code plus one Chinese sentence.
 *
 * API failures keep their server-issued code and message; anything that never
 * reached the API (offline, DNS, aborted fetch) normalises to one shared
 * network-error sentence so screens read identically.
 */

import { ApiError } from "@/lib/api";

export interface UiError {
  code: string;
  message: string;
}

export function asUiError(caught: unknown): UiError {
  return caught instanceof ApiError
    ? { code: caught.code, message: caught.message }
    : { code: "network_error", message: "网络异常，请检查连接后重试" };
}

/**
 * The one email-gate sentence, shared by every screen (spec ticket #22 wording:
 * 「请先验证邮箱」). Backend, ``uiError`` and ``authMessages`` all read the same copy.
 */
export const EMAIL_NOT_VERIFIED_MESSAGE = "请先验证邮箱后再发起 Analysis";

/**
 * Conversion-aware copy for the codes the upgrade funnel must not blur together.
 * A 429 Quota exhaustion sells the upgrade; a 403 email gate sells verification;
 * a Past Due membership sells the customer portal; a disabled platform says so.
 * ``budget_exhausted`` is the site-wide daily model budget: VIP lifts the per-user
 * Quota but not the shared cap, so its copy must never sell the upgrade.
 */
const UI_ERROR_MESSAGES: Record<string, string> = {
  quota_exhausted: "今日 Quota 已用完，升级 VIP 后 Analysis 不限次。",
  budget_exhausted: "今日服务容量已用完，请稍后再试。",
  email_not_verified: EMAIL_NOT_VERIFIED_MESSAGE,
  past_due: "订阅扣款未成功，VIP 已暂停，请前往个人中心更新支付方式。",
  too_many_requests: "尝试过于频繁，请稍后再试。",
  platform_not_enabled: "抖音暂未开放",
};

/** The sentence a screen shows for this error; unknown codes keep the server message. */
export function uiErrorMessage(error: UiError): string {
  return UI_ERROR_MESSAGES[error.code] ?? error.message;
}

/** True when this error is the "time to upgrade" moment (per-user Quota only). */
export function isQuotaExhausted(error: UiError): boolean {
  return error.code === "quota_exhausted";
}
