/**
 * Typed browser client. All shapes come from `@aab/contracts`, generated from the FastAPI
 * OpenAPI schema — there are no hand-written copies of API types in this app.
 *
 * Calls are same-origin: `next.config.ts` rewrites `/api/*` and `/media/*` to the Python API,
 * which also keeps the HttpOnly refresh cookie on its `/api/v1/auth` path.
 */
import type {
  AdminJob,
  AdminJobDetail,
  AdminJobPage,
  AdminOverview,
  AdminWork,
  AdminWorkPage,
  BookDetail,
  BookPage,
  BookProgress,
  ChapterManifest,
  Credentials,
  FeatureFlag,
  FlagValue,
  GenerateResult,
  Health,
  JobAction,
  JobStatus,
  LibraryEntry,
  LibraryPage,
  ProgressState,
  ProgressUpdate,
  ProviderInfo,
  RenderPending,
  RenderRequest,
  TokenPair,
  UploadResult,
  UserOut,
  WorkUpdate,
} from "@aab/contracts";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

/** Access token lives in memory only; the refresh token stays in an HttpOnly cookie. */
let accessToken: string | null = null;
export const setAccessToken = (token: string | null): void => {
  accessToken = token;
};
export const getAccessToken = (): string | null => accessToken;

/** Operator token is the legacy single-operator gate; kept for the zero-config launch. */
export const getAdminToken = (): string =>
  typeof window === "undefined" ? "" : localStorage.getItem("aab_token") ?? "";
export const setAdminToken = (token: string): void => {
  if (typeof window !== "undefined") localStorage.setItem("aab_token", token);
};

async function parseBody(res: Response): Promise<unknown> {
  const text = await res.text();
  if (!text) return undefined;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function errorInfo(body: unknown, fallback: string): { code: string; message: string } {
  if (body && typeof body === "object") {
    const b = body as Record<string, unknown>;
    return {
      code: typeof b.code === "string" ? b.code : "http_error",
      message:
        typeof b.message === "string"
          ? b.message
          : typeof b.detail === "string"
            ? b.detail
            : fallback,
    };
  }
  return { code: "http_error", message: fallback };
}

async function raw<T>(
  path: string,
  init: RequestInit = {},
): Promise<{ status: number; data: T }> {
  const headers = new Headers(init.headers);
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  const admin = getAdminToken();
  if (admin) headers.set("x-admin-token", admin);

  let res: Response;
  try {
    res = await fetch(path, { ...init, headers, credentials: "include" });
  } catch {
    throw new ApiError(0, "network_error", "Cannot reach the audio service. Is the API running?");
  }

  const body = await parseBody(res);
  if (!res.ok) {
    const { code, message } = errorInfo(body, `Request failed (${res.status})`);
    throw new ApiError(res.status, code, message);
  }
  return { status: res.status, data: body as T };
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  return (await raw<T>(path, init)).data;
}

const jsonPost = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  health: () => call<Health>("/api/v1/health"),

  books: (offset = 0, limit = 100) =>
    call<BookPage>(
      `/api/v1/books?${new URLSearchParams({ offset: String(offset), limit: String(limit) })}`,
    ),

  book: (id: string) => call<BookDetail>(`/api/v1/books/${encodeURIComponent(id)}`),

  upload: (form: FormData) =>
    call<UploadResult>("/api/v1/books", { method: "POST", body: form }),

  generate: (bookId: string) =>
    call<GenerateResult>(`/api/v1/books/${encodeURIComponent(bookId)}/generate`, {
      method: "POST",
    }),

  /** GET is 200 with a manifest, or 202 with the live render state. */
  renderStatus: (chapterId: string) =>
    raw<ChapterManifest | RenderPending>(
      `/api/v1/chapters/${encodeURIComponent(chapterId)}/audio`,
    ),

  render: (chapterId: string) =>
    call<RenderRequest>(`/api/v1/chapters/${encodeURIComponent(chapterId)}/audio`, {
      method: "POST",
    }),

  job: (jobId: string) => call<JobStatus>(`/api/v1/jobs/${encodeURIComponent(jobId)}`),

  register: (credentials: Credentials) =>
    call<TokenPair>("/api/v1/auth/register", jsonPost(credentials)),

  login: (credentials: Credentials) =>
    call<TokenPair>("/api/v1/auth/login", jsonPost(credentials)),

  /** Relies on the HttpOnly cookie; no Authorization header is needed. */
  refresh: () => call<TokenPair>("/api/v1/auth/refresh", { method: "POST" }),

  logout: () => call<void>("/api/v1/auth/logout", { method: "POST" }),

  me: () => call<UserOut>("/api/v1/auth/me"),

  library: () => call<LibraryPage>("/api/v1/library/"),

  libraryAdd: (workId: string) =>
    call<LibraryEntry>(`/api/v1/library/works/${encodeURIComponent(workId)}`, {
      method: "POST",
    }),

  libraryRemove: (workId: string) =>
    call<void>(`/api/v1/library/works/${encodeURIComponent(workId)}`, { method: "DELETE" }),

  progress: (chapterId: string) =>
    call<ProgressState | null>(`/api/v1/library/progress/${encodeURIComponent(chapterId)}`),

  saveProgress: (chapterId: string, update: ProgressUpdate) =>
    call<ProgressState>(`/api/v1/library/progress/${encodeURIComponent(chapterId)}`, {
      method: "PUT",
      ...jsonPost(update),
    }),

  bookProgress: (workId: string) =>
    call<BookProgress>(`/api/v1/library/works/${encodeURIComponent(workId)}/progress`),

  // ---- Phase D admin plane (canonical v1 only; gated by operator/admin credentials) ----

  adminOverview: () => call<AdminOverview>("/api/v1/admin/overview"),

  adminJobs: (
    filters: { state?: string; kind?: string; limit?: number; offset?: number } = {},
  ) => {
    const query = new URLSearchParams();
    if (filters.state) query.set("state", filters.state);
    if (filters.kind) query.set("kind", filters.kind);
    if (filters.limit !== undefined) query.set("limit", String(filters.limit));
    if (filters.offset !== undefined) query.set("offset", String(filters.offset));
    const suffix = query.toString();
    return call<AdminJobPage>(`/api/v1/admin/jobs${suffix ? `?${suffix}` : ""}`);
  },

  adminJob: (jobId: string) =>
    call<AdminJobDetail>(`/api/v1/admin/jobs/${encodeURIComponent(jobId)}`),

  adminRetryJob: (jobId: string, action: JobAction = {}) =>
    call<AdminJob>(
      `/api/v1/admin/jobs/${encodeURIComponent(jobId)}/retry`,
      jsonPost(action),
    ),

  adminCancelJob: (jobId: string, action: JobAction = {}) =>
    call<AdminJob>(
      `/api/v1/admin/jobs/${encodeURIComponent(jobId)}/cancel`,
      jsonPost(action),
    ),

  adminWorks: () => call<AdminWorkPage>("/api/v1/admin/works"),

  adminUpdateWork: (workId: string, update: WorkUpdate) =>
    call<AdminWork>(`/api/v1/admin/works/${encodeURIComponent(workId)}`, {
      method: "PATCH",
      ...jsonPost(update),
    }),

  adminFlags: () => call<FeatureFlag[]>("/api/v1/admin/flags"),

  adminSetFlag: (key: string, value: FlagValue) =>
    call<FeatureFlag>(`/api/v1/admin/flags/${encodeURIComponent(key)}`, {
      method: "PUT",
      ...jsonPost(value),
    }),

  adminDeleteFlag: (key: string, reason?: string) => {
    const query = reason ? `?${new URLSearchParams({ reason })}` : "";
    return call<void>(`/api/v1/admin/flags/${encodeURIComponent(key)}${query}`, {
      method: "DELETE",
    });
  },

  adminProviders: () => call<ProviderInfo[]>("/api/v1/admin/providers"),
};

/**
 * Refresh rotates the cookie on every call, so concurrent callers must share one request.
 * React Strict Mode mounts effects twice in development; without this, one of the two
 * refreshes can replay a token the other has already consumed and end up anonymous.
 */
let refreshInFlight: Promise<TokenPair> | null = null;
export function refreshOnce(): Promise<TokenPair> {
  if (!refreshInFlight) {
    refreshInFlight = api.refresh().finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
}

/** `<audio>` cannot send headers; the API accepts the same token as a query parameter. */
export function mediaUrl(url: string | null | undefined): string {
  if (!url) return "";
  const token = getAccessToken() || getAdminToken();
  if (!token) return url;
  return `${url}${url.includes("?") ? "&" : "?"}token=${encodeURIComponent(token)}`;
}

export function messageOf(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Something went wrong";
}
