/**
 * The single HTTP entry point for the SPA.
 *
 * - Prefixes requests with ``/api`` (override with ``VITE_API_BASE``).
 * - Attaches the in-memory access token as ``Authorization: Bearer``.
 * - On 401, refreshes the Session once (refresh token lives in an HttpOnly cookie)
 *   and retries; otherwise notifies the auth store.
 * - Parses the unified error envelope into ``ApiError { code, message, details }``.
 */

export const API_BASE: string = import.meta.env.VITE_API_BASE ?? "/api";

export interface ApiErrorEnvelope {
  error?: {
    code?: string;
    message?: string;
    details?: Record<string, unknown>;
    request_id?: string;
  };
}

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details: Record<string, unknown>;
  readonly requestId: string | null;

  constructor(
    code: string,
    message: string,
    status: number,
    details: Record<string, unknown> = {},
    requestId: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.details = details;
    this.requestId = requestId;
  }
}

export async function apiErrorFromResponse(response: Response): Promise<ApiError> {
  let code = `http_${response.status}`;
  let message = "请求失败，请稍后重试";
  let details: Record<string, unknown> = {};
  let requestId = response.headers.get("x-request-id");

  try {
    const body = (await response.json()) as ApiErrorEnvelope;
    if (body.error) {
      code = body.error.code ?? code;
      message = body.error.message ?? message;
      details = body.error.details ?? details;
      requestId = body.error.request_id ?? requestId;
    }
  } catch {
    // Non-JSON error body (e.g. nginx 502): keep the generic envelope.
  }

  return new ApiError(code, message, response.status, details, requestId);
}

let accessToken: string | null = null;
let refreshHandler: () => Promise<string | null> = refreshAccessToken;
let unauthorizedHandler: (() => void) | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}

/** Override how a new access token is obtained (tests). */
export function setTokenRefresher(handler: (() => Promise<string | null>) | null): void {
  refreshHandler = handler ?? refreshAccessToken;
}

/** Called when a 401 could not be recovered; auth store should clear local state. */
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

/** Rotate the Session using the HttpOnly refresh cookie. Shape is finalised by ticket #7. */
export async function refreshAccessToken(): Promise<string | null> {
  try {
    const response = await fetch(`${API_BASE}/auth/refresh`, {
      method: "POST",
      credentials: "same-origin",
    });
    if (!response.ok) return null;
    const body = (await response.json()) as { access_token?: string };
    return body.access_token ?? null;
  } catch {
    return null;
  }
}

async function refreshSession(): Promise<boolean> {
  try {
    const token = await refreshHandler();
    if (!token) return false;
    accessToken = token;
    return true;
  } catch {
    return false;
  }
}

export interface ApiRequestOptions {
  method?: string;
  body?: unknown;
  headers?: HeadersInit;
  signal?: AbortSignal;
  retryOn401?: boolean;
}

export function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

async function send(path: string, options: ApiRequestOptions): Promise<Response> {
  const headers = new Headers(options.headers);
  let body: BodyInit | undefined;

  if (options.body !== undefined) {
    if (
      typeof options.body === "string" ||
      options.body instanceof FormData ||
      options.body instanceof Blob ||
      options.body instanceof URLSearchParams
    ) {
      body = options.body;
    } else {
      body = JSON.stringify(options.body);
      if (!headers.has("Content-Type")) headers.set("Content-Type", "application/json");
    }
  }

  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);

  return fetch(apiUrl(path), {
    method: options.method ?? (body === undefined ? "GET" : "POST"),
    headers,
    body,
    credentials: "same-origin",
    signal: options.signal,
  });
}

export async function apiFetch<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  let response = await send(path, options);

  if (response.status === 401 && options.retryOn401 !== false) {
    const refreshed = await refreshSession();
    if (refreshed) {
      response = await send(path, { ...options, retryOn401: false });
    } else {
      unauthorizedHandler?.();
    }
  }

  if (!response.ok) throw await apiErrorFromResponse(response);
  if (response.status === 204) return undefined as T;

  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) return (await response.text()) as T;
  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string, options: Omit<ApiRequestOptions, "body"> = {}) =>
    apiFetch<T>(path, { ...options, method: "GET" }),
  post: <T>(path: string, body?: unknown, options: Omit<ApiRequestOptions, "body"> = {}) =>
    apiFetch<T>(path, { ...options, method: "POST", body }),
  patch: <T>(path: string, body?: unknown, options: Omit<ApiRequestOptions, "body"> = {}) =>
    apiFetch<T>(path, { ...options, method: "PATCH", body }),
  delete: <T>(path: string, options: Omit<ApiRequestOptions, "body"> = {}) =>
    apiFetch<T>(path, { ...options, method: "DELETE" }),
};
