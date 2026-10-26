import type { ErrorEnvelope } from "./types";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly retryAfterMs?: number,
    readonly detail: Record<string, unknown> = {},
  ) {
    super(message);
  }
}

export type Headers = Record<string, string>;

export interface Api {
  get<T>(path: string): Promise<T>;
  post<T>(path: string, body: unknown, headers?: Headers): Promise<T>;
  put<T>(path: string, body: unknown, headers?: Headers): Promise<T>;
  patch<T>(path: string, body: unknown, headers?: Headers): Promise<T>;
  del<T>(path: string, body?: unknown, headers?: Headers): Promise<T>;
}

export function createApi(base: string, token: () => string | null, onUnauthorized: () => void): Api {
  async function call<T>(method: string, path: string, body?: unknown, extra: Headers = {}): Promise<T> {
    const headers: Record<string, string> = { accept: "application/json", ...extra };
    const bearer = token();
    if (bearer) headers.authorization = "Bearer " + bearer;
    if (body !== undefined) headers["content-type"] = "application/json";
    let response: Response;
    try {
      response = await fetch(base + path, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        cache: "no-store",
        signal: AbortSignal.timeout(8000),
      });
    } catch (error) {
      throw new ApiError(0, "network", error instanceof Error ? error.message : "network error");
    }
    if (response.status === 401) {
      onUnauthorized();
      throw new ApiError(401, "unauthorized", "Sesi berakhir");
    }
    const text = await response.text();
    let parsed: unknown = null;
    try {
      parsed = text ? JSON.parse(text) : null;
    } catch {
      if (response.ok) throw new ApiError(response.status, "invalid_response", "Gateway mengirim respons yang bukan JSON");
    }
    if (!response.ok) {
      const envelope = parsed as ErrorEnvelope | null;
      const { code, message, retry_after_ms, ...detail } = envelope?.error ?? { code: "", message: "" };
      throw new ApiError(response.status, code || "http_" + response.status, message || response.statusText, retry_after_ms, detail);
    }
    return parsed as T;
  }
  return {
    get: (path) => call("GET", path),
    post: (path, body, headers) => call("POST", path, body, headers),
    put: (path, body, headers) => call("PUT", path, body, headers),
    patch: (path, body, headers) => call("PATCH", path, body, headers),
    del: (path, body, headers) => call("DELETE", path, body, headers),
  };
}
