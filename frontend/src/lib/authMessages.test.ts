import { describe, expect, it } from "vitest";

import { authErrorMessage, verificationResendNotice } from "@/lib/authMessages";
import { EMAIL_NOT_VERIFIED_MESSAGE, uiErrorMessage } from "@/lib/uiError";

describe("authErrorMessage", () => {
  it("maps stable backend codes to Chinese user-facing messages", () => {
    expect(authErrorMessage("invalid_credentials")).toBe("邮箱或密码不正确");
    expect(authErrorMessage("weak_password")).toBe("密码至少需要 8 位");
    expect(authErrorMessage("invalid_request")).toBe("请检查邮箱格式与密码");
    expect(authErrorMessage("session_invalid")).toBe("登录状态已失效，请重新登录");
    expect(authErrorMessage("auth_required")).toBe("登录状态已失效，请重新登录");
    expect(authErrorMessage("too_many_requests")).toBe("尝试过于频繁，请稍后再试");
    expect(authErrorMessage("subscription_not_found")).toBe("还没有可管理的订阅，请先完成升级支付");
  });

  it("shares the one email-gate sentence with the uiError card", () => {
    expect(authErrorMessage("email_not_verified")).toBe(EMAIL_NOT_VERIFIED_MESSAGE);
    expect(authErrorMessage("email_not_verified")).toBe(
      uiErrorMessage({ code: "email_not_verified", message: "forbidden" })
    );
  });

  it("falls back to a generic message for unknown or missing codes", () => {
    expect(authErrorMessage("something_new")).toBe("操作失败，请稍后重试");
    expect(authErrorMessage(undefined)).toBe("操作失败，请稍后重试");
  });
});

describe("verificationResendNotice", () => {
  it("shows the retryable minutes and instant when the rate limit refuses", () => {
    const notice = verificationResendNotice({ retry_after: 240, reset_at: "2026-01-16T02:15:00+00:00" });
    expect(notice).toContain("4 分钟");
    expect(notice).toContain("01-16 10:15");
  });

  it("rounds any positive retry_after up to whole minutes", () => {
    expect(verificationResendNotice({ retry_after: 5 })).toContain("1 分钟");
  });

  it("degrades gracefully when envelope details are missing", () => {
    expect(verificationResendNotice({})).toBe("发送验证邮件过于频繁，请稍后再试。");
    expect(verificationResendNotice({ reset_at: "not-a-date" })).toBe(
      "发送验证邮件过于频繁，请稍后再试。"
    );
  });
});
