import type { ErrorView } from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: ErrorView,
  ) {
    super(detail.message);
  }
}
let csrf: string | null = null;
let csrfPending: Promise<string> | null = null;
async function getCsrf(): Promise<string> {
  if (csrf) return csrf;
  if (!csrfPending)
    csrfPending = fetch("/api/v1/csrf", { credentials: "same-origin" })
      .then(async (r) => {
        if (!r.ok) throw new Error("服务暂不可用，请稍后重试");
        csrf = (await r.json()).token;
        return csrf!;
      })
      .finally(() => {
        csrfPending = null;
      });
  return csrfPending;
}
export async function api<T>(
  path: string,
  options: {
    method?: string;
    body?: unknown;
    key?: string;
    signal?: AbortSignal;
  } = {},
): Promise<T> {
  const method = options.method || "GET";
  let response: Response;
  try {
    const headers: Record<string, string> = {};
    if (method !== "GET") headers["X-CSRF-Token"] = await getCsrf();
    if (options.body !== undefined)
      headers["Content-Type"] = "application/json";
    if (options.key) headers["Idempotency-Key"] = options.key;
    response = await fetch("/api/v1" + path, {
      method,
      credentials: "same-origin",
      headers,
      body:
        options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError")
      throw error;
    throw new Error("无法连接后端服务，请检查服务状态后重试。");
  }
  if (!response.ok) {
    let detail: ErrorView;
    try {
      detail = await response.json();
    } catch {
      detail = {
        code: "SERVICE_UNAVAILABLE",
        message: "后端服务暂不可用",
        trace_id: "",
        retryable: true,
      };
    }
    if (!detail.message)
      detail = {
        code:
          response.status === 404 && /^\/runs\/[^/]+\/human-review$/.test(path)
            ? "REVIEW_API_UNAVAILABLE"
            : "SERVICE_UNAVAILABLE",
        message:
          response.status === 404 && /^\/runs\/[^/]+\/human-review$/.test(path)
            ? "当前后端尚未提供人工复核接口，请完成本地后端更新后重试。"
            : "后端服务暂不可用",
        trace_id: "",
        retryable: true,
      };
    if (detail.code === "CSRF_REJECTED") csrf = null;
    if (
      response.status === 401 &&
      !["/sessions", "/registrations", "/me"].includes(path)
    )
      window.dispatchEvent(new Event("m1-session-expired"));
    throw new ApiError(response.status, detail);
  }
  return response.status === 204 ? (undefined as T) : response.json();
}
