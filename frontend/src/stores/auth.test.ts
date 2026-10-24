import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ post: vi.fn() }));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, api: { post: mocks.post } };
});

import { ApiError } from "@/lib/api";
import { useAuthStore, type Account } from "@/stores/auth";

function account(overrides: Partial<Account> = {}): Account {
  return {
    id: "acct-1",
    email: "learner@example.com",
    created_at: "2026-01-15T08:00:00+00:00",
    email_verified_at: null,
    ...overrides,
  };
}

beforeEach(() => {
  setActivePinia(createPinia());
  vi.clearAllMocks();
});

describe("auth store email verification", () => {
  it("reports the verification state of the signed-in Account only", () => {
    const store = useAuthStore();
    expect(store.emailVerified).toBe(false);

    store.setSession("token", account());
    expect(store.emailVerified).toBe(false);

    store.setSession("token", account({ email_verified_at: "2026-01-15T09:00:00+00:00" }));
    expect(store.emailVerified).toBe(true);
  });

  it("re-sends the verification email and returns the acknowledgement", async () => {
    const store = useAuthStore();
    store.setSession("token", account());
    mocks.post.mockResolvedValue({ message: "验证邮件已发送，请查收邮箱", email_verified: false });

    const body = await store.requestVerification();

    expect(mocks.post).toHaveBeenCalledWith("/auth/verification/request", {});
    expect(body.message).toBe("验证邮件已发送，请查收邮箱");
    expect(store.emailVerified).toBe(false);
  });

  it("marks the banner resolved when the backend says the email is already verified", async () => {
    const store = useAuthStore();
    store.setSession("token", account());
    mocks.post.mockResolvedValue({ message: "邮箱已验证，无需再次发送", email_verified: true });

    const body = await store.requestVerification();

    expect(body.email_verified).toBe(true);
    expect(store.emailVerified).toBe(true);
  });

  it("propagates the frequency refusal with its retryable details intact", async () => {
    const store = useAuthStore();
    store.setSession("token", account());
    mocks.post.mockRejectedValue(
      new ApiError("too_many_requests", "尝试过于频繁，请稍后再试", 429, {
        scope: "auth.verification.request",
        retry_after: 240,
        reset_at: "2026-01-16T02:15:00+00:00",
      }),
    );

    await expect(store.requestVerification()).rejects.toMatchObject({
      code: "too_many_requests",
      details: { retry_after: 240 },
    });
  });

  it("adopts the confirmed Account so the banner clears without a re-login", async () => {
    const store = useAuthStore();
    store.setSession("token", account());
    const verified = account({ email_verified_at: "2026-01-16T01:00:00+00:00" });
    mocks.post.mockResolvedValue(verified);

    const returned = await store.confirmVerification("opaque-token");

    expect(mocks.post).toHaveBeenCalledWith(
      "/auth/verification/confirm",
      { token: "opaque-token" },
      { retryOn401: false },
    );
    expect(returned.email_verified_at).not.toBeNull();
    expect(store.emailVerified).toBe(true);
  });

  it("surfaces an invalid or expired link as a typed error for the verify page", async () => {
    const store = useAuthStore();
    mocks.post.mockRejectedValue(
      new ApiError("verification_token_expired", "验证链接已过期，请重新发送", 400),
    );

    await expect(store.confirmVerification("stale")).rejects.toMatchObject({
      code: "verification_token_expired",
    });
  });

  it("never guesses verification after logout", async () => {
    const store = useAuthStore();
    store.setSession("token", account({ email_verified_at: "2026-01-16T01:00:00+00:00" }));
    expect(store.emailVerified).toBe(true);

    store.clearSession();
    expect(store.emailVerified).toBe(false);
  });
});
