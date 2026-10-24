/**
 * The shape every UI error card reads: a machine code plus one Chinese sentence.
 *
 * API failures keep their server-issued code and message; anything that never
 * reached the API (offline, DNS, aborted fetch) normalises to one shared
 * network-error sentence so screens read identically.
 */

import { ApiError } from "@/lib/api";

export interface UiError {
  code: string;
  message: string;
}

export function asUiError(caught: unknown): UiError {
  return caught instanceof ApiError
    ? { code: caught.code, message: caught.message }
    : { code: "network_error", message: "网络异常，请检查连接后重试" };
}
