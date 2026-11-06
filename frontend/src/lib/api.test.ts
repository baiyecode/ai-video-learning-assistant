import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  api,
  getAccessToken,
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

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
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

  it("shares one Session rotation when two requests receive 401 together", async () => {
    setAccessToken("expired-token");
    const unauthorized = vi.fn(() => setAccessToken(null));
    setUnauthorizedHandler(unauthorized);
    const refresh = deferred<Response>();
    let refreshCalls = 0;
    const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      if (input.toString().endsWith("/auth/refresh")) {
        refreshCalls += 1;
        return refreshCalls === 1
          ? refresh.promise
          : errorBody("session_invalid", "登录状态已失效");
      }
      return new Headers(init?.headers).get("Authorization") === "Bearer fresh-token"
        ? json({ ok: true })
        : errorBody("auth_required", "请先登录");
    });
    vi.stubGlobal("fetch", fetchMock);

    const results = Promise.allSettled([api.get("/me/membership"), api.get("/me")]);
    await vi.waitFor(() => expect(refreshCalls).toBeGreaterThanOrEqual(1));
    refresh.resolve(json({ access_token: "fresh-token" }));

    expect(await results).toEqual([
      { status: "fulfilled", value: { ok: true } },
      { status: "fulfilled", value: { ok: true } },
    ]);
    expect(refreshCalls).toBe(1);
    expect(getAccessToken()).toBe("fresh-token");
    expect(unauthorized).not.toHaveBeenCalled();
  });

  it.each(["fresh-token", "expired-token"])(
    "retries a late old 401 using the completed refresh (%s) without rotating again",
    async (newToken) => {
      setAccessToken("expired-token");
      const lateResponse = deferred<Response>();
      const refresher = vi.fn(async () => newToken);
      setTokenRefresher(refresher);
      const authorizations: (string | null)[] = [];
      const fetchMock = vi.fn()
        .mockImplementationOnce((_input: unknown, init?: RequestInit) => {
          authorizations.push(new Headers(init?.headers).get("Authorization"));
          return lateResponse.promise;
        })
        .mockResolvedValueOnce(errorBody("auth_required", "请先登录"))
        .mockResolvedValueOnce(json({ membership: "active" }))
        .mockImplementationOnce((_input: unknown, init?: RequestInit) => {
          authorizations.push(new Headers(init?.headers).get("Authorization"));
          return Promise.resolve(json({ quota: 3 }));
        });
      vi.stubGlobal("fetch", fetchMock);

      const lateRequest = api.get("/me");
      await expect(api.get("/me/membership")).resolves.toEqual({ membership: "active" });
      lateResponse.resolve(errorBody("auth_required", "请先登录"));

      await expect(lateRequest).resolves.toEqual({ quota: 3 });
      expect(refresher).toHaveBeenCalledTimes(1);
      expect(authorizations).toEqual(["Bearer expired-token", `Bearer ${newToken}`]);
    },
  );

  it.each([null, "new-session-token"])(
    "does not revive or clear an explicitly replaced Session (%s) during refresh",
    async (replacement) => {
      setAccessToken("expired-token");
      const refresh = deferred<string | null>();
      const refresher = vi.fn(() => refresh.promise);
      setTokenRefresher(refresher);
      const unauthorized = vi.fn(() => setAccessToken(null));
      setUnauthorizedHandler(unauthorized);
      const fetchMock = vi.fn()
        .mockResolvedValueOnce(errorBody("auth_required", "请先登录"))
        .mockResolvedValue(json({ ok: true }));
      vi.stubGlobal("fetch", fetchMock);

      const request = api.get("/me");
      const result = Promise.allSettled([request]);
      await vi.waitFor(() => expect(refresher).toHaveBeenCalledTimes(1));
      setAccessToken(replacement);
      refresh.resolve("stale-refresh-token");

      expect(await result).toEqual([
        { status: "rejected", reason: expect.objectContaining({ status: 401 }) },
      ]);
      expect(getAccessToken()).toBe(replacement);
      expect(fetchMock).toHaveBeenCalledTimes(1);
      expect(unauthorized).not.toHaveBeenCalled();
    },
  );

  it("does not rotate the Session for a 401 received after local logout", async () => {
    setAccessToken("expired-token");
    const response = deferred<Response>();
    const refresher = vi.fn(async () => "stale-refresh-token");
    setTokenRefresher(refresher);
    const unauthorized = vi.fn();
    setUnauthorizedHandler(unauthorized);
    vi.stubGlobal("fetch", vi.fn(() => response.promise));

    const request = api.get("/me");
    setAccessToken(null);
    response.resolve(errorBody("auth_required", "请先登录"));

    await expect(request).rejects.toMatchObject({ status: 401 });
    expect(getAccessToken()).toBeNull();
    expect(refresher).not.toHaveBeenCalled();
    expect(unauthorized).not.toHaveBeenCalled();
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
    expect(getAccessToken()).toBeNull();
  });

  it("does not retry and notifies the store when the refresh itself fails", async () => {
    setAccessToken("expired-token");
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
    expect(getAccessToken()).toBeNull();
  });

  it("can refresh again when a later request expires after a successful rotation", async () => {
    setAccessToken("expired-token");
    const refresher = vi.fn()
      .mockResolvedValueOnce("first-refresh")
      .mockResolvedValueOnce("second-refresh");
    setTokenRefresher(refresher);
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(errorBody("auth_required", "请先登录"))
      .mockResolvedValueOnce(json({ round: 1 }))
      .mockResolvedValueOnce(errorBody("auth_required", "请先登录"))
      .mockResolvedValueOnce(json({ round: 2 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.get("/me")).resolves.toEqual({ round: 1 });
    await expect(api.get("/me")).resolves.toEqual({ round: 2 });

    expect(refresher).toHaveBeenCalledTimes(2);
    expect(getAccessToken()).toBe("second-refresh");
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it.each(["empty", "throws"])(
    "shares a failed refresh (%s), rejects both requests and permits a later attempt",
    async (failure) => {
      setAccessToken("expired-token");
      const refresh = deferred<string | null>();
      const refresher = vi.fn()
        .mockImplementationOnce(async () => {
          await refresh.promise;
          if (failure === "throws") throw new Error("network unavailable");
          return null;
        })
        .mockResolvedValueOnce("recovered-token");
      setTokenRefresher(refresher);
      const unauthorized = vi.fn();
      setUnauthorizedHandler(unauthorized);
      const fetchMock = vi.fn()
        .mockResolvedValueOnce(errorBody("auth_required", "请先登录"))
        .mockResolvedValueOnce(errorBody("auth_required", "请先登录"))
        .mockResolvedValueOnce(errorBody("auth_required", "请先登录"))
        .mockResolvedValueOnce(json({ ok: true }));
      vi.stubGlobal("fetch", fetchMock);

      const results = Promise.allSettled([api.get("/me"), api.get("/me/membership")]);
      await vi.waitFor(() => expect(refresher).toHaveBeenCalledTimes(1));
      refresh.resolve(null);

      expect(await results).toEqual([
        { status: "rejected", reason: expect.objectContaining({ status: 401 }) },
        { status: "rejected", reason: expect.objectContaining({ status: 401 }) },
      ]);
      expect(fetchMock).toHaveBeenCalledTimes(2);
      expect(getAccessToken()).toBeNull();
      expect(unauthorized).toHaveBeenCalledTimes(1);

      await expect(api.get("/me")).resolves.toEqual({ ok: true });
      expect(refresher).toHaveBeenCalledTimes(2);
      expect(getAccessToken()).toBe("recovered-token");
    },
  );

  it("aborts one waiting request promptly without cancelling the shared refresh", async () => {
    setAccessToken("expired-token");
    const refresh = deferred<string | null>();
    const refresher = vi.fn(() => refresh.promise);
    setTokenRefresher(refresher);
    const unauthorized = vi.fn();
    setUnauthorizedHandler(unauthorized);
    const controller = new AbortController();
    const fetchMock = vi.fn(async (_input: unknown, init?: RequestInit) => {
      init?.signal?.throwIfAborted();
      return new Headers(init?.headers).get("Authorization") === "Bearer fresh-token"
        ? json({ ok: true })
        : errorBody("auth_required", "请先登录");
    });
    vi.stubGlobal("fetch", fetchMock);

    const aborted = api.get("/me", { signal: controller.signal });
    const failed = vi.fn();
    const observed = aborted.catch(failed);
    const active = api.get("/me/membership");
    const results = Promise.allSettled([aborted, active]);
    await vi.waitFor(() => expect(refresher).toHaveBeenCalledTimes(1));
    controller.abort();
    try {
      await vi.waitFor(() => expect(failed).toHaveBeenCalledWith(
        expect.objectContaining({ name: "AbortError" }),
      ));
    } finally {
      refresh.resolve("fresh-token");
      await results;
      await observed;
    }

    await expect(active).resolves.toEqual({ ok: true });
    expect(refresher).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(unauthorized).not.toHaveBeenCalled();
    expect(getAccessToken()).toBe("fresh-token");
  });

  it("does not refresh a request aborted before its 401 arrives", async () => {
    setAccessToken("expired-token");
    const response = deferred<Response>();
    const refresher = vi.fn(async () => "fresh-token");
    setTokenRefresher(refresher);
    const unauthorized = vi.fn();
    setUnauthorizedHandler(unauthorized);
    const fetchMock = vi.fn(() => response.promise);
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    const request = api.get("/me", { signal: controller.signal });
    controller.abort();
    response.resolve(errorBody("auth_required", "请先登录"));

    await expect(request).rejects.toMatchObject({ name: "AbortError" });
    expect(refresher).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(unauthorized).not.toHaveBeenCalled();
    expect(getAccessToken()).toBe("expired-token");
  });

  it("honors retryOn401 false without rotating or clearing the Session", async () => {
    setAccessToken("current-token");
    const refresher = vi.fn(async () => "unused-token");
    setTokenRefresher(refresher);
    const unauthorized = vi.fn();
    setUnauthorizedHandler(unauthorized);
    const fetchMock = vi.fn().mockResolvedValue(errorBody("invalid_credentials", "邮箱或密码不正确"));
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.post("/auth/login", {}, { retryOn401: false })).rejects.toMatchObject({
      code: "invalid_credentials",
    });
    expect(refresher).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(unauthorized).not.toHaveBeenCalled();
    expect(getAccessToken()).toBe("current-token");
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
