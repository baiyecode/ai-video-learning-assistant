/**
 * The shared reader for Vite build-time arguments. One shape for "read a ``VITE_*``
 * build arg with a committed fallback", so the origin (``seo.ts``) and the numbers
 * (``lib/billing.ts``) cannot grow different rules for the same job.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { readBuildEnv, readBuildEnvNumber } from "@/lib/build-env";

describe("readBuildEnv", () => {
  it("returns the injected value for a known key", () => {
    vi.stubEnv("VITE_SITE_ORIGIN", "https://example.com");
    expect(readBuildEnv("VITE_SITE_ORIGIN")).toBe("https://example.com");
  });

  it("returns undefined when the build arg was never set", () => {
    vi.stubEnv("VITE_SITE_ORIGIN", "");
    expect(readBuildEnv("VITE_SITE_ORIGIN")).toBeUndefined();
  });
});

describe("readBuildEnvNumber", () => {
  it("parses a decimal price argument", () => {
    vi.stubEnv("VITE_SUBSCRIPTION_MONTHLY_USD", "8.50");
    expect(readBuildEnvNumber("VITE_SUBSCRIPTION_MONTHLY_USD", 4.99)).toBe(8.5);
  });

  it("falls back on absent or junk input instead of producing NaN", () => {
    vi.stubEnv("VITE_SUBSCRIPTION_MONTHLY_USD", "not-a-number");
    expect(readBuildEnvNumber("VITE_SUBSCRIPTION_MONTHLY_USD", 4.99)).toBe(4.99);
    vi.stubEnv("VITE_SUBSCRIPTION_MONTHLY_USD", "");
    expect(readBuildEnvNumber("VITE_SUBSCRIPTION_MONTHLY_USD", 4.99)).toBe(4.99);
  });

  it("falls back on a non-positive amount", () => {
    // A $0.00/月 headline or a 0-analysis free tier is a deploy typo, not a price.
    for (const junk of ["0", "-4.99"]) {
      vi.stubEnv("VITE_SUBSCRIPTION_MONTHLY_USD", junk);
      expect(readBuildEnvNumber("VITE_SUBSCRIPTION_MONTHLY_USD", 4.99)).toBe(4.99);
    }
  });

  it("rejects a fractional quota instead of silently rounding it", () => {
    // The backend models the free Quota as an int and refuses to start on 3.5; a
    // rounded 3 here would let a mistyped deploy advertise a quota nobody enforces.
    vi.stubEnv("VITE_ANALYSIS_DAILY_QUOTA", "3.5");
    expect(readBuildEnvNumber("VITE_ANALYSIS_DAILY_QUOTA", 3, { integer: true })).toBe(3);
  });

  it("accepts an integral quota written as an integer", () => {
    vi.stubEnv("VITE_ANALYSIS_DAILY_QUOTA", "5");
    expect(readBuildEnvNumber("VITE_ANALYSIS_DAILY_QUOTA", 3, { integer: true })).toBe(5);
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });
});
