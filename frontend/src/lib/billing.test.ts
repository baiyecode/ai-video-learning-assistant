import { describe, expect, it } from "vitest";

import {
  ACTIVE_STATUS,
  CANCELED_STATUS,
  FREE_STATUS,
  PAST_DUE_STATUS,
  PRICE_BENEFIT,
  PRICE_HEADLINE,
  PRICE_PROVIDER_NOTICE,
  expirationNotice,
  formatPeriodEnd,
  isVipMembership,
  membershipAlert,
  membershipStatusLabel,
  renewalNotice,
  type MembershipDto,
} from "@/lib/billing";

function membership(overrides: Partial<MembershipDto> = {}): MembershipDto {
  return {
    status: "active",
    period_end: "2026-02-14T09:00:00+00:00",
    portal_url: null,
    is_vip: true,
    ...overrides,
  };
}

describe("membership helpers", () => {
  it("mirrors only the backend-derived VIP flag", () => {
    expect(isVipMembership(membership())).toBe(true);
    expect(isVipMembership(membership({ status: "past_due", is_vip: false }))).toBe(false);
    expect(isVipMembership(membership({ status: FREE_STATUS, is_vip: false }))).toBe(false);
    expect(isVipMembership(null)).toBe(false);
  });

  it("warns Past Due accounts to fix their payment method", () => {
    const alert = membershipAlert(membership({ status: "past_due", is_vip: false }));
    expect(alert).toContain("扣款未成功");
  });

  it("previews the VIP end date for an ending trial", () => {
    const alert = membershipAlert(
      membership({ status: "trial_ending", period_end: "2026-02-14T09:00:00+00:00" })
    );
    expect(alert).toBe("试用会员将于 2月14日 到期，之后恢复免费额度。");
  });

  it("shifts the period end into the Asia/Shanghai calendar day", () => {
    // 20:00 UTC is already the next calendar day in Shanghai.
    expect(formatPeriodEnd("2026-02-14T20:00:00+00:00")).toBe("2月15日");
    expect(formatPeriodEnd(null)).toBeNull();
  });

  it("stays quiet for healthy and free memberships", () => {
    expect(membershipAlert(membership())).toBeNull();
    expect(membershipAlert(membership({ status: FREE_STATUS, period_end: null, is_vip: false }))).toBeNull();
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
  });

  it("previews the VIP loss for a canceled subscription still inside its period", () => {
    const notice = expirationNotice(
      membership({ status: CANCELED_STATUS, period_end: futureIso(), is_vip: false })
    );
    expect(notice).toContain("订阅已取消");
    expect(notice).toContain("届时失去 VIP");
  });

  it("previews the VIP loss date for an ending trial", () => {
    const notice = expirationNotice(membership({ status: "trial_ending", period_end: futureIso() }));
    expect(notice).toMatch(/^将于 .+ 失去 VIP。$/);
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
