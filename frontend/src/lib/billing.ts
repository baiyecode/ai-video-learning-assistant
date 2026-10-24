/**
 * Subscription DTO and presentation helpers for the Account's membership.
 *
 * Mirrors `GET /api/me/membership`: the backend is the only subscription truth and
 * VIP is the backend-derived flag (status-based, never a stored column, never a
 * checkout redirect parameter). These helpers only render what that response says.
 */

export interface MembershipDto {
  status: string;
  period_end: string | null;
  portal_url: string | null;
  is_vip: boolean;
}

export const FREE_STATUS = "free";
export const PAST_DUE_STATUS = "past_due";
export const TRIAL_ENDING_STATUS = "trial_ending";

export function isVipMembership(membership: MembershipDto | null): boolean {
  return membership?.is_vip === true;
}

/** Short Asia/Shanghai calendar day for membership notices, e.g. "2月14日". */
export function formatPeriodEnd(iso: string | null): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  const parts = new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "numeric",
    day: "numeric",
  }).formatToParts(date);
  const month = parts.find((part) => part.type === "month")?.value ?? "";
  const day = parts.find((part) => part.type === "day")?.value ?? "";
  return `${month}月${day}日`;
}

/**
 * The one alert line the UI shows above the membership block, or null.
 *
 * - Past Due: payment trouble warning (story 11).
 * - Trial ending with a known end: the "VIP ends on ..." preview (story 9).
 */
export function membershipAlert(membership: MembershipDto | null): string | null {
  if (!membership) return null;
  if (membership.status === PAST_DUE_STATUS) {
    return "订阅扣款未成功，VIP 已暂停，请前往订阅管理更新支付方式。";
  }
  if (membership.status === TRIAL_ENDING_STATUS && membership.period_end) {
    const day = formatPeriodEnd(membership.period_end);
    return day ? `试用会员将于 ${day} 到期，之后恢复免费额度。` : null;
  }
  return null;
}
