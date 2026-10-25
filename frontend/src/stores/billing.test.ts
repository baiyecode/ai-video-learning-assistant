import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, api: { get: mocks.get, post: mocks.post } };
});

import { ApiError } from "@/lib/api";
import type { MembershipDto } from "@/lib/billing";
import { useBillingStore } from "@/stores/billing";

const FREE: MembershipDto = {
  status: "free",
  period_end: null,
  cancel_at_period_end: false,
  is_vip: false,
};

function membership(overrides: Partial<MembershipDto> = {}): MembershipDto {
  return {
    status: "active",
    period_end: "2026-02-14T08:00:00+00:00",
    cancel_at_period_end: false,
    is_vip: true,
    ...overrides,
  };
}

beforeEach(() => {
  setActivePinia(createPinia());
  vi.clearAllMocks();
});

describe("billing store", () => {
  it("loads the Account membership from /me/membership", async () => {
    mocks.get.mockResolvedValue(FREE);

    const store = useBillingStore();
    await store.loadMembership();

    expect(mocks.get).toHaveBeenCalledWith("/me/membership");
    expect(store.membership).toEqual(FREE);
    expect(store.isVip).toBe(false);
    expect(store.loading).toBe(false);
    expect(store.error).toBeNull();
  });

  it("reads VIP from the backend-derived membership flag", async () => {
    mocks.get.mockResolvedValue(membership());
    const store = useBillingStore();
    await store.loadMembership();
    expect(store.isVip).toBe(true);

    mocks.get.mockResolvedValue(membership({ status: "past_due", is_vip: false }));
    await store.loadMembership();
    expect(store.isVip).toBe(false);
  });

  it("never guesses VIP from a checkout redirect: with no membership loaded isVip is false", async () => {
    const store = useBillingStore();
    expect(store.isVip).toBe(false);

    mocks.get.mockRejectedValue(new ApiError("auth_required", "请先登录", 401));
    await store.loadMembership();
    expect(store.isVip).toBe(false);
  });

  it("surfaces the API message when membership cannot be loaded", async () => {
    mocks.get.mockRejectedValue(new ApiError("auth_required", "请先登录", 401));

    const store = useBillingStore();
    await store.loadMembership();

    expect(store.membership).toBeNull();
    expect(store.error).toBe("请先登录");
    expect(store.loading).toBe(false);
  });

  it("mints a checkout URL for the full-page upgrade jump", async () => {
    mocks.post.mockResolvedValue({ url: "https://checkout.stripe.test/session_123" });

    const store = useBillingStore();
    const url = await store.openCheckout();

    expect(mocks.post).toHaveBeenCalledWith("/billing/checkout", {});
    expect(url).toBe("https://checkout.stripe.test/session_123");
  });

  it("propagates a failed checkout without touching membership", async () => {
    mocks.post.mockRejectedValue(
      new ApiError("service_unavailable", "支付通道暂未就绪，请稍后重试", 503),
    );

    const store = useBillingStore();
    await expect(store.openCheckout()).rejects.toThrow(ApiError);
    expect(store.membership).toBeNull();
  });

  it("mints a customer portal URL for subscription management", async () => {
    mocks.post.mockResolvedValue({ url: "https://portal.stripe.test/billing_1" });

    const store = useBillingStore();
    const url = await store.openPortal();

    expect(mocks.post).toHaveBeenCalledWith("/billing/portal", {});
    expect(url).toBe("https://portal.stripe.test/billing_1");
  });

  it("treats a re-read after the checkout redirect as the only truth", async () => {
    mocks.get.mockResolvedValue(FREE);
    const store = useBillingStore();
    await store.loadMembership();
    expect(store.isVip).toBe(false);

    // The browser is back from Stripe: the store flips to VIP only because the
    // fresh /me/membership read says so — never because of a redirect parameter.
    mocks.get.mockResolvedValue(membership());
    await store.loadMembership();
    expect(store.isVip).toBe(true);
    expect(store.membership?.status).toBe("active");
  });
});
