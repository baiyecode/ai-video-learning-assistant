import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api";
import { asUiError, isQuotaExhausted, uiErrorMessage } from "@/lib/uiError";

describe("uiErrorMessage", () => {
  it("keeps the 429 Quota exhaustion distinct as an upgrade moment", () => {
    const error = asUiError(new ApiError("quota_exhausted", "今日 Quota 已用完", 429));
    expect(uiErrorMessage(error)).toContain("升级 VIP");
    expect(isQuotaExhausted(error)).toBe(true);
  });

  it("keeps the 403 email gate distinct as a verification moment", () => {
    const error = asUiError(new ApiError("email_not_verified", "forbidden", 403));
    expect(uiErrorMessage(error)).toBe("请先验证邮箱后再发起 Analysis");
    expect(uiErrorMessage(error)).not.toContain("Quota");
  });

  it("routes a Past Due membership to the payment-method fix, not to a generic 403", () => {
    const error = asUiError(new ApiError("past_due", "forbidden", 403));
    expect(uiErrorMessage(error)).toContain("扣款未成功");
    expect(uiErrorMessage(error)).toContain("更新支付方式");
  });

  it("names the disabled platform instead of a generic unsupported URL", () => {
    const error = asUiError(new ApiError("platform_not_enabled", "unsupported", 422));
    expect(uiErrorMessage(error)).toBe("抖音暂未开放");
  });

  it("treats budget exhaustion as an upgrade moment too", () => {
    const error = asUiError(new ApiError("budget_exhausted", "预算已用完", 429));
    expect(isQuotaExhausted(error)).toBe(true);
    expect(uiErrorMessage(error)).toContain("不限次");
  });

  it("falls back to the server message for codes the funnel does not own", () => {
    const error = asUiError(new ApiError("resolve_failed", "解析失败，请稍后重试", 502));
    expect(uiErrorMessage(error)).toBe("解析失败，请稍后重试");
    expect(isQuotaExhausted(error)).toBe(false);
  });

  it("keeps the shared network sentence for failures that never reached the API", () => {
    const error = asUiError(new TypeError("fetch failed"));
    expect(error.code).toBe("network_error");
    expect(uiErrorMessage(error)).toBe("网络异常，请检查连接后重试");
  });
});
