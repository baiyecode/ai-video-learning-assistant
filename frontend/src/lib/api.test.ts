import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  api,
  setAccessToken,
  setTokenRefresher,
  setUnauthorizedHandler,
} from "@/lib/api";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function errorBody(code: string, message: string): Response {
  return json({ error: { code, message, details: {}, request_id: "req-1" } }, 401);
}

afterEach(() => {
  vi.unstubAllGlobals();
  setAccessToken(null);
  setTokenRefresher(null);
  setUnauthorizedHandler(null);
});

describe("api auth handling", () => {
  it("refreshes once on a token-less 401 and retries with the new Bearer token", async () => {
    const calls: { url: string; authorization: string | null }[] = [];
    const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      calls.push({
        url,
        authorization: new Headers(init?.headers).get("Authorization"),
      });
      if (url.endsWith("/auth/refresh")) return json({ access_token: "fresh-token" });
      if (calls.length === 1) return errorBody("auth_required", "请先登录");
      return json({ account: { id: "a1", email: "a@example.com" } });
    });
    vi.stubGlobal("fetch", fetchMock);

    const body = await api.get<{ account: { id: string } }>("/me");

    expect(body.account.id).toBe("a1");
    expect(calls.map((call) => call.url)).toEqual(["/api/me", "/api/auth/refresh", "/api/me"]);
    expect(calls[0]?.authorization).toBeNull();
    expect(calls[1]?.authorization).toBeNull();
    expect(calls[2]?.authorization).toBe("Bearer fresh-token");
  });

  it("refreshes at most once per request and reports the failure", async () => {
    const unauthorized = vi.fn();
    setUnauthorizedHandler(unauthorized);
    let refreshCalls = 0;
    const fetchMock = vi.fn(async (input: string | URL | Request) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.endsWith("/auth/refresh")) {
        refreshCalls += 1;
        return json({ access_token: "fresh-token" });
      }
      return errorBody("auth_required", "请先登录");
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.get("/me")).rejects.toMatchObject({
      code: "auth_required",
      status: 401,
    });

    expect(refreshCalls).toBe(1);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(unauthorized).toHaveBeenCalledTimes(1);
  });

  it("does not retry and notifies the store when the refresh itself fails", async () => {
    const unauthorized = vi.fn();
    setUnauthorizedHandler(unauthorized);
    const fetchMock = vi.fn(async (input: string | URL | Request) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.endsWith("/auth/refresh")) {
        return json({ error: { code: "session_invalid", message: "登录状态已失效" } }, 401);
      }
      return errorBody("auth_required", "请先登录");
    });
    vi.stubGlobal("fetch", fetchMock);

    const attempt = api.get("/me");

    await expect(attempt).rejects.toBeInstanceOf(ApiError);
    await expect(attempt).rejects.toMatchObject({ code: "auth_required" });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(unauthorized).toHaveBeenCalledTimes(1);
  });

  it("uses the injected refresher instead of the network when one is installed", async () => {
    const refresher = vi.fn(async () => "seam-token");
    setTokenRefresher(refresher);
    const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url === "/api/me" && new Headers(init?.headers).get("Authorization")) {
        return json({ ok: true });
      }
      return errorBody("auth_required", "请先登录");
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.get("/me")).resolves.toEqual({ ok: true });

    expect(refresher).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
