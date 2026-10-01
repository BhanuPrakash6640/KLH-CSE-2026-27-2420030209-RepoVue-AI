/** Shapes returned by the RepoVue API (app/schemas/api.py).
 *  Kept hand-written rather than generated so the field comments survive. */

export type Severity = "critical" | "high" | "medium" | "low" | "info";

export type Category = "logical_bug" | "security" | "performance" | "architecture";

export type FindingStatusValue =
  | "open"
  | "patch_proposed"
  | "validated"
  | "rejected"
  | "false_positive"
  | "resolved";

export type AnalysisStatusValue =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled";

export type Verdict = "pass" | "fail" | "skipped" | "error";

export interface Repository {
  id: string;
  provider: string;
  full_name: string;
  clone_url: string;
  default_branch: string;
  is_private: boolean;
  created_at: string;
}

/** Written by the pipeline stage by stage; every key is optional because a run
 *  that failed at stage 1 has almost none of them. */
export interface AnalysisStats {
  commit_sha?: string;
  changed_files?: number;
  files_analysed?: number;
  loc?: number;
  symbols?: number;
  languages?: Record<string, number>;
  project?: Record<string, unknown>;
  graph?: Record<string, number>;
  dependency_cycles?: number;
  chunks?: number;
  files_reviewed?: number;
  raw_findings?: number;
  findings?: number;
  findings_dropped_by_triage?: number;
  by_severity?: Record<string, number>;
  by_category?: Record<string, number>;
  patches_generated?: number;
  patches_validated?: number;
  jira_tickets?: number;
  fix_pr_url?: string;
  duration_sec?: number;
  llm_usage?: Record<string, number>;
  review_skipped?: string;
  publish_skipped?: string;
  publish_error?: string;
  options?: { open_pr?: boolean; categories?: Category[] };
  [key: string]: unknown;
}

export interface Analysis {
  id: string;
  repository_id: string;
  repository_full_name: string | null;
  commit_sha: string | null;
  branch: string | null;
  pr_number: number | null;
  trigger: string;
  status: AnalysisStatusValue;
  stage: string | null;
  progress: number;
  error: string | null;
  stats: AnalysisStats;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface AnalysisSummary {
  analysis: Analysis;
  repository: Repository | null;
  findings_by_severity: Record<string, number>;
  findings_by_category: Record<string, number>;
  patches: Record<string, number>;
  top_files: { path: string; findings: number }[];
}

export interface RepositoryOverview {
  repository: Repository;
  last_analysis: Analysis | null;
  findings: number;
  patched: number;
  validated: number;
  false_positives: number;
  by_severity: Record<string, number>;
}

export interface Patch {
  id: string;
  finding_id: string;
  analysis_id: string;
  path: string;
  diff: string;
  explanation: string | null;
  risk_notes: string | null;
  status: "generated" | "validating" | "accepted" | "rejected" | "published";
  model: string | null;
  created_at: string;
}

/** Baseline and patched sides of a validation run. The sandbox writes whatever
 *  it could measure, so treat every field as best-effort. */
export interface ValidationSide {
  passed?: boolean;
  tests_passed?: number;
  tests_failed?: number;
  total?: number;
  duration_sec?: number;
  median_sec?: number;
  exit_code?: number;
  summary?: string;
  [key: string]: unknown;
}

export interface ValidationRun {
  id: string;
  patch_id: string;
  image_tag: string | null;
  test_command: string | null;
  tests_passed: boolean;
  perf_delta_pct: number | null;
  verdict: Verdict;
  reason: string | null;
  baseline: ValidationSide;
  patched: ValidationSide;
  logs: string | null;
  created_at: string;
}

export interface Finding {
  id: string;
  analysis_id: string;
  category: Category;
  severity: Severity;
  confidence: number;
  title: string;
  description: string;
  root_cause: string | null;
  impact: string | null;
  path: string;
  start_line: number;
  end_line: number;
  snippet: string | null;
  cwe: string | null;
  owasp: string | null;
  tags: string[];
  evidence: Record<string, unknown>;
  status: FindingStatusValue;
  model: string | null;
  created_at: string;
}

export interface FindingDetail extends Finding {
  patches: Patch[];
}

export interface FindingPage {
  total: number;
  limit: number;
  offset: number;
  items: Finding[];
}

export interface SearchHit {
  path: string;
  symbol_name: string | null;
  start_line: number;
  end_line: number;
  score: number;
  content: string;
}

export interface QualityGate {
  analysis_id: string;
  status: AnalysisStatusValue;
  complete: boolean;
  passed: boolean;
  stage: string | null;
  progress: number;
  fail_on: string;
  blocking_findings: number;
  counts: Record<string, number>;
  patches: Record<string, number>;
  error: string | null;
}

export interface Health {
  status: string;
  env: string;
  database: string;
  llm_configured: boolean;
  docker: string;
  version: string;
}

export interface Metrics {
  repositories: number;
  analyses: number;
  findings: number;
  findings_by_severity: Record<string, number>;
  false_positives: number;
  jobs_pending: number;
  jobs_failed: number;
}

export interface JiraTicket {
  key: string;
  url: string;
  status: string;
}

export interface SourceFileRow {
  path: string;
  language: string | null;
  loc: number;
  parse_error: string | null;
}

export interface GraphInfo {
  metrics: Record<string, number>;
  cycles: number;
  project: Record<string, unknown>;
  languages: Record<string, number>;
}

export interface ChatMessage {
  role: "user" | "assistant" | "system";
  content: string;
}

export interface ChatFindingRef {
  id: string;
  title: string;
  category: Category;
  severity: Severity;
  path: string;
  start_line: number;
  end_line: number;
  cwe?: string | null;
}

export interface ChatRequest {
  query: string;
  analysis_id?: string | null;
  finding_id?: string | null;
  history?: ChatMessage[];
}

export interface ChatResponse {
  response: string;
  suggested_questions: string[];
  referenced_findings: ChatFindingRef[];
  provider: string;
}
