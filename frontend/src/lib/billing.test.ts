import { describe, expect, it } from "vitest";

import {
  FREE_STATUS,
  formatPeriodEnd,
  isVipMembership,
  membershipAlert,
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
