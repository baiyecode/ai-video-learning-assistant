/**
 * Fetch-based Server-Sent Events.
 *
 * ``EventSource`` cannot send the ``Authorization`` header, so analysis streams use
 * ``fetch`` + a manual parser. ``connectSse`` reconnects with backoff on connection
 * failures and sends ``Last-Event-ID`` so the server can replay missed events.
 */

import { ApiError, apiErrorFromResponse, getAccessToken } from "@/lib/api";

export interface SseMessage {
  event: string;
  data: string;
  id: string | null;
}

const BLOCK_SEPARATOR = /\r\n\r\n|\n\n|\r\r/;
const LINE_SEPARATOR = /\r\n|\r|\n/;

export async function* parseSseStream(
  stream: ReadableStream<Uint8Array>,
  signal?: AbortSignal,
): AsyncGenerator<SseMessage> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  const onAbort = () => {
    void reader.cancel().catch(() => undefined);
  };
  signal?.addEventListener("abort", onAbort, { once: true });

  let buffer = "";
  let lastEventId: string | null = null;

  try {
    while (true) {
      if (signal?.aborted) return;
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let match = BLOCK_SEPARATOR.exec(buffer);
      while (match) {
        const block = buffer.slice(0, match.index);
        buffer = buffer.slice(match.index + match[0].length);
        const message = parseBlock(block, lastEventId);
        if (message) {
          lastEventId = message.id;
          yield message;
        }
        match = BLOCK_SEPARATOR.exec(buffer);
      }
    }

    buffer += decoder.decode();
    const trailing = parseBlock(buffer, lastEventId);
    if (trailing) yield trailing;
  } finally {
    signal?.removeEventListener("abort", onAbort);
    try {
      await reader.cancel();
    } catch {
      // Stream already errored/closed.
    }
    reader.releaseLock();
  }
}

function parseBlock(block: string, previousId: string | null): SseMessage | null {
  if (!block) return null;

  let event = "message";
  let id = previousId;
  const data: string[] = [];

  for (const line of block.split(LINE_SEPARATOR)) {
    if (!line || line.startsWith(":")) continue;
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);

    if (field === "event") {
      event = value;
    } else if (field === "data") {
      data.push(value);
    } else if (field === "id" && !value.includes("\u0000")) {
      id = value;
    }
  }

  // Events without data are keep-alives (or comments) and are not dispatched.
  if (data.length === 0) return null;
  return { event: event || "message", data: data.join("\n"), id };
}

export interface SseConnectOptions {
  method?: "GET" | "POST";
  headers?: Record<string, string>;
  body?: BodyInit | null;
  signal?: AbortSignal;
  /** Injectable for tests; defaults to global fetch. */
  fetchImpl?: typeof fetch;
  maxRetries?: number;
  baseRetryDelayMs?: number;
  sleep?: (ms: number) => Promise<void>;
}

export async function* connectSse(
  url: string,
  options: SseConnectOptions = {},
): AsyncGenerator<SseMessage> {
  const fetchImpl = options.fetchImpl ?? fetch;
  const sleep =
    options.sleep ?? ((ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms)));
  const maxRetries = options.maxRetries ?? 3;
  const baseDelay = options.baseRetryDelayMs ?? 500;

  let lastEventId: string | null = null;
  let attempt = 0;

  while (true) {
    const headers = new Headers(options.headers);
    headers.set("Accept", "text/event-stream");
    const token = getAccessToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
    if (lastEventId) headers.set("Last-Event-ID", lastEventId);

    let response: Response;
    try {
      response = await fetchImpl(url, {
        method: options.method ?? "GET",
        headers,
        body: options.body,
        credentials: "same-origin",
        signal: options.signal,
      });
    } catch (error) {
      if (options.signal?.aborted || attempt >= maxRetries) throw error;
      attempt += 1;
      await sleep(backoffDelay(attempt, baseDelay));
      continue;
    }

    if (!response.ok) {
      const apiError = await apiErrorFromResponse(response);
      if (response.status >= 500 && attempt < maxRetries) {
        attempt += 1;
        await sleep(backoffDelay(attempt, baseDelay));
        continue;
      }
      throw apiError;
    }

    if (!response.body) {
      throw new ApiError("stream_failed", "服务器未返回事件流", response.status);
    }

    try {
      for await (const message of parseSseStream(response.body, options.signal)) {
        if (message.id) lastEventId = message.id;
        yield message;
      }
      return;
    } catch (error) {
      if (options.signal?.aborted || attempt >= maxRetries) throw error;
      attempt += 1;
      await sleep(backoffDelay(attempt, baseDelay));
    }
  }
}

function backoffDelay(attempt: number, baseDelayMs: number): number {
  return baseDelayMs * 2 ** Math.max(0, attempt - 1);
}
