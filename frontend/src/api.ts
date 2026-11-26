// Thin client for the FastAPI backend. Every call is same-origin (Vite proxies /api), so the
// HttpOnly session cookie is sent automatically and never touched by JavaScript.

export type Role = "viewer" | "analyst" | "admin";
export interface User { id: string; email: string; role: Role; created_at: string }
export interface Dataset { id: string; name: string; status: string; row_count: number; created_at: string }
export interface Job {
  id: string; kind: string; status: "queued" | "running" | "succeeded" | "failed"; attempts: number;
  result: Record<string, unknown> | null; error: { code: string; message: string; [k: string]: unknown } | null;
  created_at: string; started_at: string | null; finished_at: string | null;
}
export interface Transaction {
  id: string; dataset_id: string; external_ref: string; account_id: string; occurred_at: string;
  amount: string; currency: string; merchant: string; category: string;
}
export interface Assessment {
  transaction_id: string; external_ref: string; account_id: string; occurred_at: string; amount: string;
  currency: string; merchant: string; category: string; risk_score: number; is_flagged: boolean; reasons: string[];
}
export interface Summary {
  totals: { currency: string; count: number; total: string; average: string; min: string; max: string }[];
  by_category: { category: string; currency: string; count: number; total: string }[];
}
export interface Doc { id: string; filename: string; status: string; page_count: number; chunk_count: number; created_at: string }
export interface Citation { source: string; filename: string; page: number; excerpt: string; score: number }
export interface Answer {
  status: string; answer: string | null; reason: string | null; citations: Citation[];
  model: string | null; latency_ms: number;
}
export interface Evidence {
  transaction_id: string; account_id: string; occurred_at: string; amount: string; currency: string;
  merchant: string; category: string; risk_score: number | null; flagged: boolean | null; reasons?: string[];
}
export interface ReportContent {
  summary: string; recommendation: string; disclaimer: string; wording_flag: boolean;
  dropped_findings: number; tool_calls: number;
  findings: { transaction_id: string; observation: string; evidence: Evidence }[];
  policy_refs: { id: string; filename: string; page: number; excerpt: string }[];
}
export interface Report {
  id: string; owner_id: string; dataset_id: string; status: "draft" | "submitted" | "approved" | "rejected";
  focus: string; content: ReportContent; model: string; created_at: string; submitted_at: string | null;
  reviewed_by: string | null; reviewed_at: string | null; review_note: string | null;
}
export interface Step { attempt: number; step: number; tool: string; status: string; error: string | null; result_chars: number; latency_ms: number }

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public requestId?: string, public body?: unknown) {
    super(message);
  }
}

type Query = Record<string, string | number | boolean | undefined | null>;

async function call<T>(method: string, path: string, opts: { json?: unknown; body?: BodyInit; headers?: Record<string, string>; query?: Query } = {}): Promise<T> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(opts.query ?? {})) if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  const headers: Record<string, string> = { ...opts.headers };
  let body = opts.body;
  if (opts.json !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(opts.json); }
  const res = await fetch(`/api/v1${path}${qs.size ? `?${qs}` : ""}`, { method, headers, body, credentials: "same-origin" });
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const err = data?.error ?? {};
    throw new ApiError(res.status, err.code ?? `http_${res.status}`, err.message ?? res.statusText, err.request_id, data);
  }
  return data as T;
}

const key = () => ({ "Idempotency-Key": crypto.randomUUID() });

export const api = {
  me: () => call<User>("GET", "/auth/me"),
  login: (email: string, password: string) => call<User>("POST", "/auth/login", { json: { email, password } }),
  logout: () => call<void>("POST", "/auth/logout"),
  datasets: () => call<Dataset[]>("GET", "/datasets", { query: { limit: 100 } }),
  deleteDataset: (id: string) => call<void>("DELETE", `/datasets/${id}`),
  uploadDataset: (file: File, name: string) =>
    call<Job>("POST", "/datasets", { query: { name }, body: file, headers: { "Content-Type": "text/csv", ...key() } }),
  job: (id: string) => call<Job>("GET", `/jobs/${id}`),
  score: (datasetId: string) => call<Job>("POST", "/risk-assessments", { json: { dataset_id: datasetId } }),
  transactions: (q: Query) => call<{ items: Transaction[]; next_cursor: string | null }>("GET", "/transactions", { query: q }),
  summary: (q: Query) => call<Summary>("GET", "/analytics/summary", { query: q }),
  flagged: (datasetId: string, offset: number) =>
    call<Assessment[]>("GET", "/risk-assessments", { query: { dataset_id: datasetId, flagged_only: true, limit: 50, offset } }),
  documents: () => call<Doc[]>("GET", "/documents", { query: { limit: 100 } }),
  uploadDocument: async (file: File) => {
    const res = await call<Job | Doc>("POST", "/documents", { query: { name: file.name }, body: file, headers: { "Content-Type": "application/pdf" } });
    return res;
  },
  ask: (question: string) => call<Answer>("POST", "/answers", { json: { question } }),
  investigate: (datasetId: string, focus: string) =>
    call<Job>("POST", "/investigations", { json: { dataset_id: datasetId, focus }, headers: key() }),
  reports: () => call<Report[]>("GET", "/reports", { query: { limit: 100 } }),
  report: (id: string) => call<Report>("GET", `/reports/${id}`),
  steps: (id: string) => call<Step[]>("GET", `/reports/${id}/steps`),
  submit: (id: string) => call<Report>("POST", `/reports/${id}/submit`),
  approve: (id: string, note: string) => call<Report>("POST", `/reports/${id}/approve`, { json: { note: note || null } }),
  reject: (id: string, note: string) => call<Report>("POST", `/reports/${id}/reject`, { json: { note: note || null } }),
};

/** Poll a job until it finishes. `onTick` gets every intermediate state (for progress text). */
export async function waitForJob(id: string, onTick?: (job: Job) => void, intervalMs = 1000): Promise<Job> {
  for (;;) {
    const job = await api.job(id);
    onTick?.(job);
    if (job.status === "succeeded" || job.status === "failed") return job;
    await new Promise((r) => setTimeout(r, intervalMs));
  }
}

export function errorText(e: unknown): string {
  if (e instanceof ApiError) return `${e.message}${e.requestId ? ` (request ${e.requestId.slice(0, 8)})` : ""}`;
  return e instanceof Error ? e.message : String(e);
}
