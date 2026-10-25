import type { Connection, PullProgress, SystemStatus, Task, TaskEvent } from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

/** Turns whatever the service returned into one plain sentence. */
export function errorMessage(status: number, body: unknown): string {
  if (status === 401) return "The app is not allowed to talk to the Karyakarta service. Restart Karyakarta.";
  if (status === 429) return "Too many tasks are waiting. Wait for some to finish.";
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string" && detail) return detail;
  if (Array.isArray(detail) && detail.length) {
    const first = detail[0] as { msg?: string; loc?: unknown[] };
    const field = Array.isArray(first.loc) ? String(first.loc[first.loc.length - 1]) : "";
    if (field === "instruction") return "Describe the task in a few words (up to 2000 characters).";
    if (field === "start_url") return "The starting address is too long.";
    return first.msg ?? "The request was not valid.";
  }
  return `The service returned an error (${status}).`;
}

export class Api {
  constructor(private conn: Connection, private fetchFn: typeof fetch = (...a) => fetch(...a)) {}

  private headers(json = false): Record<string, string> {
    return { "X-Karyakarta-Token": this.conn.token, ...(json ? { "Content-Type": "application/json" } : {}) };
  }

  private async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    let res: Response;
    try {
      res = await this.fetchFn(this.conn.baseUrl + path, {
        method,
        headers: this.headers(body !== undefined),
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch {
      throw new ApiError(0, "Cannot reach the Karyakarta service. It may still be starting.");
    }
    if (res.status === 204) return undefined as T;
    let data: unknown = null;
    try {
      data = await res.json();
    } catch {
      /* no body */
    }
    if (!res.ok) throw new ApiError(res.status, errorMessage(res.status, data));
    return data as T;
  }

  health = () => this.request<{ ok: boolean; version: string }>("GET", "/api/health");
  status = () => this.request<SystemStatus>("GET", "/api/system/status");
  listTasks = () => this.request<Task[]>("GET", "/api/tasks");
  getTask = (id: number) => this.request<Task>("GET", `/api/tasks/${id}`);
  getEvents = (id: number, after = 0) => this.request<TaskEvent[]>("GET", `/api/tasks/${id}/events?after=${after}`);
  createTask = (instruction: string, startUrl: string) =>
    this.request<Task>("POST", "/api/tasks", { instruction, start_url: startUrl.trim() || null });
  cancel = (id: number) => this.request<{ ok: boolean }>("POST", `/api/tasks/${id}/cancel`);
  confirm = (id: number, approved: boolean) => this.request<{ ok: boolean }>("POST", `/api/tasks/${id}/confirm`, { approved });
  sendCredential = (id: number, value: string) => this.request<{ ok: boolean }>("POST", `/api/tasks/${id}/credential`, { value });
  answer = (id: number, message: string) => this.request<{ ok: boolean }>("POST", `/api/tasks/${id}/answer`, { message });
  remove = (id: number) => this.request<void>("DELETE", `/api/tasks/${id}`);

  /** The activity stream address. The token travels in the query because browsers cannot set headers on a WebSocket. */
  streamUrl(id: number, after: number): string {
    const base = this.conn.baseUrl.replace(/^http/, "ws");
    return `${base}/api/ws/tasks/${id}?token=${encodeURIComponent(this.conn.token)}&after=${after}`;
  }

  async screenshot(taskId: number, path: string): Promise<Blob> {
    const name = path.split("/").pop() ?? path;
    const res = await this.fetchFn(`${this.conn.baseUrl}/api/tasks/${taskId}/screenshots/${encodeURIComponent(name)}`, {
      headers: this.headers(),
    });
    if (!res.ok) throw new ApiError(res.status, "Screenshot not available.");
    return res.blob();
  }

  /** Downloads the model, reporting progress as it streams in. */
  async pullModel(onProgress: (p: PullProgress) => void): Promise<void> {
    let res: Response;
    try {
      res = await this.fetchFn(`${this.conn.baseUrl}/api/system/model/pull`, { method: "POST", headers: this.headers() });
    } catch {
      throw new ApiError(0, "Cannot reach the Karyakarta service.");
    }
    if (!res.ok || !res.body) throw new ApiError(res.status, errorMessage(res.status, null));
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let newline: number;
      while ((newline = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, newline).trim();
        buffer = buffer.slice(newline + 1);
        if (!line) continue;
        const progress = JSON.parse(line) as PullProgress;
        onProgress(progress);
        if (progress.status === "error") throw new ApiError(500, progress.error ?? "The model download failed.");
      }
    }
  }
}
