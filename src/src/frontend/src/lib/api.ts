import type {
  Analysis,
  AnalysisSummary,
  Category,
  ChatRequest,
  ChatResponse,
  Finding,
  FindingDetail,
  FindingPage,
  FindingStatusValue,
  GraphInfo,
  Health,
  JiraTicket,
  Metrics,
  Patch,
  QualityGate,
  Repository,
  RepositoryOverview,
  SearchHit,
  SourceFileRow,
  ValidationRun,
} from "./types";

const BASE = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");
const PREFIX = `${BASE}/api/v1`;
const KEY_STORAGE = "repovue.apiKey";

/** The key lives in localStorage so one browser can point at a shared
 *  deployment without a rebuild. Falls back to the build-time default. */
export function getApiKey(): string {
  return (
    window.localStorage.getItem(KEY_STORAGE) ??
    import.meta.env.VITE_API_KEY ??
    "dev-local-key"
  );
}

export function setApiKey(key: string): void {
  window.localStorage.setItem(KEY_STORAGE, key.trim());
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

async function request<T>(
  path: string,
  init: RequestInit & { query?: Record<string, unknown> } = {},
): Promise<T> {
  const { query, ...rest } = init;
  let url = `${PREFIX}${path}`;
  if (query) {
    const params = new URLSearchParams();
    for (const [k, v] of Object.entries(query)) {
      if (v !== undefined && v !== null && v !== "") params.set(k, String(v));
    }
    const qs = params.toString();
    if (qs) url += `?${qs}`;
  }

  let response: Response;
  try {
    response = await fetch(url, {
      ...rest,
      headers: {
        "Content-Type": "application/json",
        "X-API-Key": getApiKey(),
        ...(rest.headers ?? {}),
      },
    });
  } catch {
    // A network-level failure is nearly always the API not running, and that
    // is a more useful thing to say than "Failed to fetch".
    throw new ApiError(0, "Cannot reach the API. Is it running?");
  }

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  const body = text ? safeJson(text) : null;

  if (!response.ok) {
    throw new ApiError(response.status, detailOf(body) ?? `Request failed (${response.status})`);
  }
  return body as T;
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return { detail: text.slice(0, 300) };
  }
}

/** FastAPI returns `detail` as a string, or as a list of validation errors. */
function detailOf(body: unknown): string | null {
  if (!body || typeof body !== "object") return null;
  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const first = detail[0] as { msg?: string; loc?: unknown[] } | undefined;
    if (first?.msg) {
      const field = Array.isArray(first.loc) ? first.loc[first.loc.length - 1] : null;
      return field ? `${field}: ${first.msg}` : first.msg;
    }
  }
  return null;
}

export interface FindingQuery {
  [key: string]: unknown;
  analysis_id?: string;
  severity?: string;
  category?: string;
  status?: string;
  path?: string;
  q?: string;
  limit?: number;
  offset?: number;
}

export interface AnalysisRequest {
  url?: string;
  repository_id?: string;
  branch?: string | null;
  commit_sha?: string | null;
  pr_number?: number | null;
  diff_only?: boolean;
  open_pr?: boolean;
  categories?: Category[];
}

export const api = {
  health: () => request<Health>("/health"),
  metrics: () => request<Metrics>("/metrics"),

  repositories: () => request<Repository[]>("/repositories"),
  repositoriesOverview: () => request<RepositoryOverview[]>("/repositories/overview"),
  repository: (id: string) => request<Repository>(`/repositories/${id}`),
  registerRepository: (url: string) =>
    request<Repository>("/repositories", { method: "POST", body: JSON.stringify({ url }) }),

  analyses: (query: { repository_id?: string; status?: string; limit?: number } = {}) =>
    request<Analysis[]>("/analyses", { query }),
  analysis: (id: string) => request<Analysis>(`/analyses/${id}`),
  summary: (id: string) => request<AnalysisSummary>(`/analyses/${id}/summary`),
  files: (id: string) => request<SourceFileRow[]>(`/analyses/${id}/files`),
  graph: (id: string) => request<GraphInfo>(`/analyses/${id}/graph`),
  gate: (id: string, failOn = "high") =>
    request<QualityGate>(`/analyses/${id}/gate`, { query: { fail_on: failOn } }),
  startAnalysis: (payload: AnalysisRequest) =>
    request<Analysis>("/analyses", { method: "POST", body: JSON.stringify(payload) }),
  deleteAnalysis: (id: string) => request<void>(`/analyses/${id}`, { method: "DELETE" }),

  findings: (query: FindingQuery) => request<FindingPage>("/findings", { query }),
  finding: (id: string) => request<FindingDetail>(`/findings/${id}`),
  updateFinding: (id: string, status: FindingStatusValue, note?: string) =>
    request<FindingDetail>(`/findings/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ status, note: note ?? null }),
    }),
  jira: (findingId: string) => request<JiraTicket>(`/findings/${findingId}/jira`),

  patches: (query: { analysis_id?: string; status?: string; limit?: number } = {}) =>
    request<Patch[]>("/patches", { query }),
  patch: (id: string) => request<Patch>(`/patches/${id}`),
  validations: (patchId: string) => request<ValidationRun[]>(`/patches/${patchId}/validations`),
  decidePatch: (id: string, accept: boolean) =>
    request<Patch>(`/patches/${id}/decision`, { method: "POST", query: { accept } }),

  search: (analysis_id: string, query: string, limit = 10) =>
    request<SearchHit[]>("/search", {
      method: "POST",
      body: JSON.stringify({ analysis_id, query, limit }),
    }),

  chat: (payload: ChatRequest) =>
    request<ChatResponse>("/chat", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};

export type { Finding };
