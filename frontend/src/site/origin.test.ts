/**
 * Build-time site origin: only a bare absolute http(s) origin may be baked into
 * canonical/OG/sitemap; anything else must fail the build with the variable and
 * the offending value named. No network, no Vite build.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { DEFAULT_DEV_ORIGIN, resolveSiteOrigin } from "@/site/seo";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("resolveSiteOrigin", () => {
  it.each([
    "https://example.com",
    "http://localhost:8080",
    "https://example.com:8443",
    "https://sub.example.co.uk",
    "https://xn--fiqs8s.example",
  ])("accepts the bare origin %s unchanged", (value) => {
    expect(resolveSiteOrigin(value)).toBe(value);
  });

  it.each([
    ["https://example.com/path", /path/],
    ["https://example.com/articles/x", /path/],
    ["https://example.com?utm=1", /query/],
    ["https://example.com/?utm=1", /query/],
    ["https://example.com#top", /hash/],
    ["https://example.com/", /trailing slash/],
    ["https://example.com:8443/", /trailing slash/],
    ["ftp://example.com", /http/],
    ["file:///tmp/site", /http/],
    ["https://user:secret@example.com", /credentials/],
    ["https://user@example.com", /credentials/],
    ["https://", /host|invalid/i],
    ["example.com", /absolute|invalid/i],
    ["//example.com", /absolute|invalid/i],
    ["https://exa mple.com", /invalid/i],
  ])("rejects %s and names VITE_SITE_ORIGIN and the value", (value, reason) => {
    const call = () => resolveSiteOrigin(value);

    expect(call).toThrow(/VITE_SITE_ORIGIN/);
    expect(call).toThrow(reason);
    expect(call).toThrow(JSON.stringify(value).slice(1, -1));
  });

  it("falls back to the Vite dev origin with a warning when unset", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});

    expect(resolveSiteOrigin(undefined)).toBe(DEFAULT_DEV_ORIGIN);
    expect(resolveSiteOrigin("")).toBe(DEFAULT_DEV_ORIGIN);
    expect(resolveSiteOrigin("   ")).toBe(DEFAULT_DEV_ORIGIN);

    expect(warn).toHaveBeenCalled();
    expect(warn.mock.calls.flat().join(" ")).toMatch(/VITE_SITE_ORIGIN/);
    expect(warn.mock.calls.flat().join(" ")).toContain(DEFAULT_DEV_ORIGIN);
  });

  it("does not warn for a valid origin", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});

    resolveSiteOrigin("https://example.com");

    expect(warn).not.toHaveBeenCalled();
  });
});
