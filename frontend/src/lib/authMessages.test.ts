import { describe, expect, it } from "vitest";

import { authErrorMessage } from "@/lib/authMessages";

describe("authErrorMessage", () => {
  it("maps stable backend codes to Chinese user-facing messages", () => {
    expect(authErrorMessage("invalid_credentials")).toBe("邮箱或密码不正确");
    expect(authErrorMessage("email_taken")).toBe("该邮箱已注册，请直接登录");
    expect(authErrorMessage("weak_password")).toBe("密码至少需要 8 位");
    expect(authErrorMessage("invalid_request")).toBe("请检查邮箱格式与密码");
    expect(authErrorMessage("session_invalid")).toBe("登录状态已失效，请重新登录");
    expect(authErrorMessage("auth_required")).toBe("登录状态已失效，请重新登录");
    expect(authErrorMessage("too_many_requests")).toBe("尝试过于频繁，请稍后再试");
    expect(authErrorMessage("subscription_not_found")).toBe("还没有可管理的订阅，请先完成升级支付");
  });

  it("falls back to a generic message for unknown or missing codes", () => {
    expect(authErrorMessage("something_new")).toBe("操作失败，请稍后重试");
    expect(authErrorMessage(undefined)).toBe("操作失败，请稍后重试");
  });
});
