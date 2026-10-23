import { describe, expect, it } from "vitest";

import {
  REPORT_REASONS,
  toReportPayload,
  validateReport,
  type ReportFormInput,
} from "@/lib/report";

function input(overrides: Partial<ReportFormInput> = {}): ReportFormInput {
  return { url: "", reason: "copyright", contact: "", details: "", ...overrides };
}

describe("report form validation", () => {
  it("accepts every offered reason with only a reason filled in", () => {
    expect(REPORT_REASONS.map((reason) => reason.value)).toEqual([
      "copyright",
      "drm_bypass",
      "abuse",
      "other",
    ]);
    for (const reason of REPORT_REASONS) {
      expect(validateReport(input({ reason: reason.value }))).toBeNull();
    }
  });

  it("requires choosing an allowed reason", () => {
    expect(validateReport(input({ reason: "" }))).toBe("请选择举报原因");
    expect(validateReport(input({ reason: "unknown" }))).toBe("请选择举报原因");
  });

  it("only accepts http(s) report URLs", () => {
    expect(validateReport(input({ url: "ftp://example.com/a" }))).toBe(
      "举报链接需为 http 或 https 地址",
    );
    expect(validateReport(input({ url: "not a url" }))).toBe("举报链接需为 http 或 https 地址");
    expect(validateReport(input({ url: "https://example.com/a" }))).toBeNull();
    expect(validateReport(input({ url: "http://example.com/a" }))).toBeNull();
  });

  it("enforces the same length limits as the API", () => {
    expect(validateReport(input({ contact: "a".repeat(257) }))).toBe("联系方式最多 256 个字符");
    expect(validateReport(input({ details: "字".repeat(2001) }))).toBe("详情最多 2000 个字符");
    expect(validateReport(input({ url: `https://example.com/${"a".repeat(2048)}` }))).toBe(
      "举报链接过长",
    );
  });

  it("trims values and omits blank optional fields from the payload", () => {
    expect(
      toReportPayload(input({ url: "  https://example.com/a  ", contact: "  ", details: "  侵权  " })),
    ).toEqual({
      reason: "copyright",
      url: "https://example.com/a",
      details: "侵权",
    });
    expect(toReportPayload(input())).toEqual({ reason: "copyright" });
  });
});
