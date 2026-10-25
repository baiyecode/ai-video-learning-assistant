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
  /** Provider's scheduled cancellation: VIP is kept until ``period_end`` (story 8). */
  cancel_at_period_end: boolean;
  vip_active: boolean;
}

export const FREE_STATUS = "free";
export const ACTIVE_STATUS = "active";
export const PAST_DUE_STATUS = "past_due";
export const TRIAL_ENDING_STATUS = "trial_ending";
export const CANCELED_STATUS = "canceled";

/**
 * The single monthly plan (spec: "$4.99/月、Analysis 不限次").
 * Mirrors backend ``Settings.subscription_monthly_usd``; the hosted checkout page of
 * the payment provider is the final word on the charged amount (已注明「以支付方为准」).
 */
export const MONTHLY_PRICE_USD = 4.99;
export const PRICE_HEADLINE = `$${MONTHLY_PRICE_USD.toFixed(2)}/月`;
export const PRICE_BENEFIT = "Analysis 不限次";
export const PRICE_PROVIDER_NOTICE = "以上为当前标价，实际扣款以支付方（Stripe）结账页展示的条款为准。";

/**
 * Mirrors backend ``Settings.analysis_daily_quota``: the free Analysis Quota.
 * The single source for the "每日 N 次" copy so a quota change is one edit.
 */
export const DAILY_FREE_ANALYSIS_LIMIT = 3;
export const FREE_DAILY_ANALYSIS_LABEL = `每日 ${DAILY_FREE_ANALYSIS_LIMIT} 次 Analysis`;

const STATUS_LABELS: Record<string, string> = {
  [FREE_STATUS]: "免费版",
  [ACTIVE_STATUS]: "VIP 订阅中",
  [PAST_DUE_STATUS]: "扣款未成功，VIP 已暂停",
  [TRIAL_ENDING_STATUS]: "试用中",
  [CANCELED_STATUS]: "已取消订阅",
};

export function membershipStatusLabel(membership: MembershipDto | null): string {
  if (!membership) return "订阅状态加载中";
  return STATUS_LABELS[membership.status] ?? membership.status;
}

/** True when ``period_end`` is strictly in the future relative to ``now``. */
export function periodEndInFuture(iso: string | null, now: Date = new Date()): boolean {
  if (!iso) return false;
  const end = new Date(iso);
  return !Number.isNaN(end.getTime()) && end.getTime() > now.getTime();
}

/** "下次续费日期" for a running subscription, or null when nothing renews. */
export function renewalNotice(membership: MembershipDto | null): string | null {
  if (!membership || membership.status !== ACTIVE_STATUS) return null;
  if (membership.cancel_at_period_end) return null;
  const day = formatPeriodEnd(membership.period_end);
  return day ? `下次续费日期：${day}` : null;
}

/**
 * The "到期预告" shown once access is winding down (stories 8/9):
 * only while the Account truly still holds VIP — ``vip_active`` with the status in
 * ``active``/``trial_ending`` and ``period_end`` ahead of now. A scheduled
 * cancellation (``cancel_at_period_end``) promises the retention end date; a
 * trial promises its loss date. Past Due sells the portal fix and a real
 * cancellation is already non-VIP: neither gets a retention preview.
 */
export function expirationNotice(membership: MembershipDto | null): string | null {
  if (!membership || !membership.vip_active) return null;
  const withinPaidPeriod =
    membership.status === ACTIVE_STATUS || membership.status === TRIAL_ENDING_STATUS;
  if (!withinPaidPeriod) return null;
  if (!membership.period_end || !periodEndInFuture(membership.period_end)) return null;
  const day = formatPeriodEnd(membership.period_end);
  if (!day) return null;
  if (membership.cancel_at_period_end) {
    return `已取消续费，VIP 将保留至 ${day}，届时将失去 VIP 并恢复免费 Quota。`;
  }
  if (membership.status === TRIAL_ENDING_STATUS) {
    return `将于 ${day} 失去 VIP。`;
  }
  return null;
}

export function hasVipMembership(membership: MembershipDto | null): boolean {
  return membership?.vip_active === true;
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
    return day ? `试用会员将于 ${day} 到期，之后恢复免费 Quota。` : null;
  }
  return null;
}
