export type TaskStatus = "queued" | "running" | "awaiting_user" | "completed" | "failed" | "cancelled";

export const TERMINAL: ReadonlySet<TaskStatus> = new Set(["completed", "failed", "cancelled"]);

export interface Step {
  idx: number;
  url: string | null;
  thought: string | null;
  action: string | null;
  mark: number | null;
  summary: string | null;
  ok: number;
  verified: number;
  detail: { changed?: boolean; outcome?: string; notes?: string[] };
  model_ms: number | null;
  tokens_out: number | null;
  screenshot: string | null;
  ts: number;
}

export interface Task {
  id: number;
  instruction: string;
  start_url: string | null;
  status: TaskStatus;
  result: string | null;
  error: string | null;
  model: string | null;
  created_at: number;
  started_at: number | null;
  finished_at: number | null;
  steps?: Step[];
}

export type EventKind =
  | "task_queued"
  | "task_started"
  | "observe"
  | "thought"
  | "policy"
  | "action"
  | "step_result"
  | "warning"
  | "notice"
  | "confirmation_request"
  | "credential_request"
  | "question"
  | "task_complete"
  | "task_error"
  | "task_cancelled"
  | "ping";

export interface TaskEvent {
  task_id: number;
  seq: number;
  ts: number;
  kind: EventKind;
  message: string;
  detail: Record<string, unknown>;
}

export interface SystemStatus {
  version: string;
  engine_running: boolean;
  engine_version: string | null;
  model: string;
  model_installed: boolean;
  browser_installed: boolean;
  ready: boolean;
  current_task: number | null;
}

export interface PullProgress {
  status: string;
  percent: number | null;
  error?: string;
}

export interface Connection {
  baseUrl: string;
  token: string;
}

/** A picture of the page the agent was looking at, with where it was. */
export interface Shot {
  idx: number;
  screenshot: string;
  url: string | null;
}
