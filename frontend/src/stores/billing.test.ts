import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, api: { get: mocks.get } };
});

import { ApiError } from "@/lib/api";
import type { MembershipDto } from "@/lib/billing";
import { useBillingStore } from "@/stores/billing";

const FREE: MembershipDto = {
  status: "free",
  period_end: null,
  portal_url: null,
  is_vip: false,
};

function membership(overrides: Partial<MembershipDto> = {}): MembershipDto {
  return {
    status: "active",
    period_end: "2026-02-14T08:00:00+00:00",
    portal_url: null,
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
});
