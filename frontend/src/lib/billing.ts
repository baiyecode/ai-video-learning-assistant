/**
 * Subscription DTO and presentation helpers for the Account's membership.
 *
 * Mirrors `GET /api/me/membership`: the backend is the only subscription truth and
 * VIP is the backend-derived flag (status-based, never a stored column, never a
 * checkout redirect parameter). These helpers only render what that response says.
 */

import { readBuildEnvNumber } from "@/lib/build-env";
import {
  DEFAULT_DAILY_FREE_ANALYSIS_LIMIT,
  DEFAULT_MONTHLY_PRICE_USD,
} from "@/lib/billing-defaults";

export { DEFAULT_DAILY_FREE_ANALYSIS_LIMIT, DEFAULT_MONTHLY_PRICE_USD };

export interface MembershipDto {
  status: string;
  period_end: string | null;
  /** Provider's scheduled cancellation: VIP is kept until ``period_end`` (story 8). */
  cancel_at_period_end: boolean;
  vip_active: boolean;
  /**
   * Portal *entry* path minted per call by ``POST /billing/portal`` — never a
   * provider-hosted link, and identical for every status. Only an Account that holds a
   * managed subscription gets an entry point on the UI (issue #44 follow-up):
   * ``portalEntryVisibleFor()`` is the single rule.
   */
  portal_url: string;
  /** Display monthly price in USD from the running server's ``Settings`` (ticket #41). */
  monthly_price_usd: number;
  /** Free daily Analysis Quota the server actually enforces (same source). */
  daily_free_analysis_limit: number;
}

export const FREE_STATUS = "free";
export const ACTIVE_STATUS = "active";
export const PAST_DUE_STATUS = "past_due";
export const TRIAL_ENDING_STATUS = "trial_ending";
export const CANCELED_STATUS = "canceled";

/**
 * The single monthly plan (spec: "$4.99/月、Analysis 不限次").
 * Derived from ``VITE_SUBSCRIPTION_MONTHLY_USD`` (mirrors backend
 * ``Settings.subscription_monthly_usd``) through the shared build-arg reader. For a
 * signed-in Account the runtime source wins: ``priceHeadline()`` renders the price the
 * server reported on ``/me/membership``, so a deployment started with a different
 * ``APP_SUBSCRIPTION_MONTHLY_USD`` cannot show a stale literal. The hosted checkout page
 * of the payment provider remains the final word on the charged amount (已注明「以支付方为准」).
 */
export const MONTHLY_PRICE_USD = readBuildEnvNumber(
  "VITE_SUBSCRIPTION_MONTHLY_USD",
  DEFAULT_MONTHLY_PRICE_USD,
);
export const PRICE_HEADLINE = `$${MONTHLY_PRICE_USD.toFixed(2)}/月`;
export const PRICE_BENEFIT = "Analysis 不限次";
export const PRICE_PROVIDER_NOTICE = "以上为当前标价，实际扣款以支付方（Stripe）结账页展示的条款为准。";

/**
 * The free Analysis Quota, derived from ``VITE_ANALYSIS_DAILY_QUOTA`` (mirrors backend
 * ``Settings.analysis_daily_quota``, the value the API actually enforces). The single
 * build-time source for the "每日 N 次" copy, so repricing the Quota is one deploy-env
 * edit and a quota change can no longer leave the marketing/discovery copy behind.
 * ``integer`` because the backend field is an ``int``: a fractional deploy arg is refused
 * (fallback) instead of rounded, so the copy never advertises an allowance the server
 * would reject.
 */
export const DAILY_FREE_ANALYSIS_LIMIT = readBuildEnvNumber(
  "VITE_ANALYSIS_DAILY_QUOTA",
  DEFAULT_DAILY_FREE_ANALYSIS_LIMIT,
  { integer: true },
);
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

/**
 * The monthly display price the UI renders: the running server's ``Settings`` value as
 * reported by ``GET /me/membership``, falling back to the build-time mirror while the
 * read is pending (and for prerendered marketing, where there is no payload at all).
 * One pair of functions, so no view re-derives a price literal.
 */
export function monthlyPriceUsdFor(membership: MembershipDto | null): number {
  return membership?.monthly_price_usd ?? MONTHLY_PRICE_USD;
}

export function priceHeadlineFor(membership: MembershipDto | null): string {
  return `$${monthlyPriceUsdFor(membership).toFixed(2)}/月`;
}

/** The free Quota the server enforces, with the same build-time fallback. */
export function dailyFreeAnalysisLimitFor(membership: MembershipDto | null): number {
  return membership?.daily_free_analysis_limit ?? DAILY_FREE_ANALYSIS_LIMIT;
}

export function freeDailyAnalysisLabelFor(membership: MembershipDto | null): string {
  return `每日 ${dailyFreeAnalysisLimitFor(membership)} 次 Analysis`;
}

/**
 * Whether the UI may offer the billing portal entry. The backend reports ``portal_url``
 * for every status (the managed link is minted by the POST), and ``POST /billing/portal``
 * answers ``404 subscription_not_found`` only when the Account has no Subscription record
 * at all — so the entry follows "holds a managed subscription": any status other than
 * ``free`` (``active`` / ``trial_ending`` / ``past_due`` / ``canceled``). The Past Due
 * dunning copy points at 订阅管理, and a ``past_due`` Account is by definition not
 * ``vip_active`` (issue #44 follow-up); gating on VIP would hide the fix from exactly
 * the person it addresses. Un-subscribed and signed-out Accounts still get no entry.
 */
export function portalEntryVisibleFor(membership: MembershipDto | null): boolean {
  return (
    membership !== null && membership.status !== FREE_STATUS && Boolean(membership.portal_url)
  );
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
