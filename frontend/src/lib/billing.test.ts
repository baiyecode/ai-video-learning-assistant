import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ACTIVE_STATUS,
  CANCELED_STATUS,
  DAILY_FREE_ANALYSIS_LIMIT,
  DEFAULT_DAILY_FREE_ANALYSIS_LIMIT,
  DEFAULT_MONTHLY_PRICE_USD,
  FREE_DAILY_ANALYSIS_LABEL,
  FREE_STATUS,
  PAST_DUE_STATUS,
  PRICE_BENEFIT,
  PRICE_HEADLINE,
  PRICE_PROVIDER_NOTICE,
  expirationNotice,
  formatPeriodEnd,
  hasVipMembership,
  membershipAlert,
  membershipStatusLabel,
  renewalNotice,
  type MembershipDto,
} from "@/lib/billing";

const FRONTEND_ROOT = path.resolve(fileURLToPath(new URL("../..", import.meta.url)));
const REPO_ROOT = path.resolve(FRONTEND_ROOT, "..");

function membership(overrides: Partial<MembershipDto> = {}): MembershipDto {
  return {
    status: "active",
    period_end: "2026-02-14T09:00:00+00:00",
    cancel_at_period_end: false,
    vip_active: true,
    ...overrides,
  };
}

describe("membership helpers", () => {
  it("mirrors only the backend-derived VIP flag", () => {
    expect(hasVipMembership(membership())).toBe(true);
    expect(hasVipMembership(membership({ status: "past_due", vip_active: false }))).toBe(false);
    expect(hasVipMembership(membership({ status: FREE_STATUS, vip_active: false }))).toBe(false);
    expect(hasVipMembership(null)).toBe(false);
  });

  it("warns Past Due accounts to fix their payment method", () => {
    const alert = membershipAlert(membership({ status: "past_due", vip_active: false }));
    expect(alert).toContain("扣款未成功");
  });

  it("previews the VIP end date for an ending trial", () => {
    const alert = membershipAlert(
      membership({ status: "trial_ending", period_end: "2026-02-14T09:00:00+00:00" })
    );
    expect(alert).toBe("试用会员将于 2月14日 到期，之后恢复免费 Quota。");
  });

  it("shifts the period end into the Asia/Shanghai calendar day", () => {
    // 20:00 UTC is already the next calendar day in Shanghai.
    expect(formatPeriodEnd("2026-02-14T20:00:00+00:00")).toBe("2月15日");
    expect(formatPeriodEnd(null)).toBeNull();
  });

  it("stays quiet for healthy and free memberships", () => {
    expect(membershipAlert(membership())).toBeNull();
    expect(membershipAlert(membership({ status: FREE_STATUS, period_end: null, vip_active: false }))).toBeNull();
    expect(membershipAlert(null)).toBeNull();
  });
});

function futureIso(days = 5): string {
  return new Date(Date.now() + days * 86_400_000).toISOString();
}

describe("pricing copy", () => {
  it("carries the single monthly clause with the provider-terms disclaimer", () => {
    expect(PRICE_HEADLINE).toBe("$4.99/月");
    expect(PRICE_BENEFIT).toBe("Analysis 不限次");
    expect(PRICE_PROVIDER_NOTICE).toContain("以支付方");
  });

  it("derives the free-quota sentence from the single limit constant", () => {
    expect(DAILY_FREE_ANALYSIS_LIMIT).toBe(3);
    expect(FREE_DAILY_ANALYSIS_LABEL).toBe("每日 3 次 Analysis");
  });

  it("derives price and free Quota from the injected VITE_ build-time values", async () => {
    // A repricing/re-quota deploy rebuilds the static marketing with new VITE_ args;
    // every consumer (pricing page, sitemap, llms.txt, descriptors) follows automatically.
    vi.resetModules();
    vi.stubEnv("VITE_SUBSCRIPTION_MONTHLY_USD", "8.50");
    vi.stubEnv("VITE_ANALYSIS_DAILY_QUOTA", "5");
    const fresh = await import("@/lib/billing");
    expect(fresh.MONTHLY_PRICE_USD).toBe(8.5);
    expect(fresh.PRICE_HEADLINE).toBe("$8.50/月");
    expect(fresh.DAILY_FREE_ANALYSIS_LIMIT).toBe(5);
    expect(fresh.FREE_DAILY_ANALYSIS_LABEL).toBe("每日 5 次 Analysis");
  });

  it("falls back to the committed defaults when the VITE_ values are absent or junk", async () => {
    vi.resetModules();
    vi.stubEnv("VITE_SUBSCRIPTION_MONTHLY_USD", "");
    vi.stubEnv("VITE_ANALYSIS_DAILY_QUOTA", "not-a-number");
    const fresh = await import("@/lib/billing");
    expect(fresh.MONTHLY_PRICE_USD).toBe(DEFAULT_MONTHLY_PRICE_USD);
    expect(fresh.DAILY_FREE_ANALYSIS_LIMIT).toBe(DEFAULT_DAILY_FREE_ANALYSIS_LIMIT);
  });

  it("keeps the fallbacks equal to the backend Settings the API actually enforces", () => {
    // The single repricing knob lives in the deploy env; these committed defaults are
    // only the local/dev fallback. This test reads the independent backend source so a
    // drifted default fails loudly instead of letting the discovery layer silently lie.
    const config = readFileSync(path.join(REPO_ROOT, "backend", "app", "config.py"), "utf8");
    const quota = config.match(/analysis_daily_quota:\s*int\s*=\s*(\d+)/);
    const price = config.match(/subscription_monthly_usd:\s*float\s*=\s*([\d.]+)/);
    expect(quota, "analysis_daily_quota default missing from backend config").not.toBeNull();
    expect(price, "subscription_monthly_usd default missing from backend config").not.toBeNull();
    expect(Number(quota![1])).toBe(DEFAULT_DAILY_FREE_ANALYSIS_LIMIT);
    expect(Number(price![1])).toBe(DEFAULT_MONTHLY_PRICE_USD);
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
  });
});

describe("membership status presentation", () => {
  it("labels each lifecycle status in Chinese", () => {
    expect(membershipStatusLabel(membership({ status: FREE_STATUS }))).toBe("免费版");
    expect(membershipStatusLabel(membership({ status: ACTIVE_STATUS }))).toBe("VIP 订阅中");
    expect(membershipStatusLabel(membership({ status: PAST_DUE_STATUS }))).toBe("扣款未成功，VIP 已暂停");
    expect(membershipStatusLabel(membership({ status: CANCELED_STATUS }))).toBe("已取消订阅");
    expect(membershipStatusLabel(null)).toBe("订阅状态加载中");
  });

  it("shows the renewal date only for a running subscription", () => {
    expect(renewalNotice(membership({ status: ACTIVE_STATUS }))).toBe("下次续费日期：2月14日");
    expect(renewalNotice(membership({ status: CANCELED_STATUS }))).toBeNull();
    expect(renewalNotice(membership({ status: ACTIVE_STATUS, period_end: null }))).toBeNull();
    // A scheduled cancellation renews nothing.
    expect(
      renewalNotice(membership({ status: ACTIVE_STATUS, cancel_at_period_end: true }))
    ).toBeNull();
  });

  it("previews the VIP loss for a scheduled cancellation still inside its period", () => {
    const notice = expirationNotice(
      membership({ cancel_at_period_end: true, period_end: futureIso() })
    );
    expect(notice).toContain("取消续费");
    expect(notice).toContain("保留至");
    expect(notice).toContain("失去 VIP");
  });

  it("previews the VIP loss date for an ending trial", () => {
    const notice = expirationNotice(membership({ status: "trial_ending", period_end: futureIso() }));
    expect(notice).toMatch(/^将于 .+ 失去 VIP。$/);
  });

  it("only previews retention while the account truly still holds VIP", () => {
    // Past Due sells the portal fix, not a retention promise (spec Story 11/12).
    expect(
      expirationNotice(
        membership({
          status: PAST_DUE_STATUS,
          vip_active: false,
          cancel_at_period_end: true,
          period_end: futureIso(),
        })
      )
    ).toBeNull();
    // A real deletion is already non-VIP: no 「保留至」 promise anymore (Story 8/9 split).
    expect(
      expirationNotice(membership({ status: CANCELED_STATUS, vip_active: false, period_end: futureIso() }))
    ).toBeNull();
  });

  it("says nothing once the period has passed or for healthy/free states", () => {
    expect(
      expirationNotice(membership({ status: CANCELED_STATUS, period_end: "2020-01-01T00:00:00+00:00" }))
    ).toBeNull();
    expect(expirationNotice(membership({ status: FREE_STATUS, period_end: null }))).toBeNull();
    expect(expirationNotice(membership())).toBeNull();
    expect(expirationNotice(null)).toBeNull();
  });
});
