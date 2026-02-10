/**
 * API client with auth token management.
 */

const BASE_URL = "/api/miniapp";

let _token: string | null = null;

export function setToken(token: string) {
  _token = token;
}

export function getToken(): string | null {
  return _token;
}

export function clearToken() {
  _token = null;
}

interface ApiResponse<T = unknown> {
  ok: boolean;
  data?: T;
  error?: { code: string; message: string };
}

export async function apiFetch<T = unknown>(
  path: string,
  options: RequestInit = {}
): Promise<ApiResponse<T>> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };

  if (_token) {
    headers["Authorization"] = `Bearer ${_token}`;
  }

  const res = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers,
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const detail = body.detail || body;
    throw {
      status: res.status,
      code: detail?.error?.code || "UNKNOWN",
      message: detail?.error?.message || res.statusText,
    };
  }

  return res.json();
}

/**
 * Create an EventSource-like SSE reader for POST requests.
 * Returns an async generator yielding parsed SSE data objects.
 */
export async function* apiStream<T = unknown>(
  path: string,
  body: object
): AsyncGenerator<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };

  if (_token) {
    headers["Authorization"] = `Bearer ${_token}`;
  }

  const res = await fetch(`${BASE_URL}${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw {
      status: res.status,
      code: err.detail?.error?.code || "UNKNOWN",
      message: err.detail?.error?.message || res.statusText,
    };
  }

  const reader = res.body?.getReader();
  if (!reader) return;

  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    // Parse SSE lines
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (line.startsWith("data: ")) {
        try {
          const data = JSON.parse(line.slice(6));
          yield data as T;
        } catch {
          // skip malformed lines
        }
      }
    }
  }
}
