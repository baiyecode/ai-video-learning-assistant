import { describe, expect, it } from "vitest";

import { PASSWORD_MIN_LENGTH, validatePassword } from "@/lib/validation";

describe("validatePassword", () => {
  it("requires at least 8 characters with no composition rules", () => {
    expect(PASSWORD_MIN_LENGTH).toBe(8);
    expect(validatePassword("")).toBe("密码至少需要 8 位");
    expect(validatePassword("1234567")).toBe("密码至少需要 8 位");
    expect(validatePassword("12345678")).toBeNull();
    expect(validatePassword("abcdefgh")).toBeNull();
  });

  it("counts Unicode code points rather than UTF-16 units", () => {
    expect(validatePassword("密码密码密码密")).toBe("密码至少需要 8 位");
    expect(validatePassword("密码密码密码密码")).toBeNull();
  });
});
