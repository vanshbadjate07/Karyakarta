import type { TaskEvent, TaskStatus } from "./types";

export const TERMINAL_EVENTS = new Set(["task_complete", "task_error", "task_cancelled"]);

/** Adds new events, drops repeats (a reconnect replays history) and keeps order. */
export function mergeEvents(prev: TaskEvent[], incoming: TaskEvent[]): TaskEvent[] {
  const bySeq = new Map<number, TaskEvent>();
  for (const e of prev) bySeq.set(e.seq, e);
  for (const e of incoming) if (e.kind !== "ping") bySeq.set(e.seq, e);
  return [...bySeq.values()].sort((a, b) => a.seq - b.seq);
}

export const lastSeq = (events: TaskEvent[]): number => (events.length ? events[events.length - 1].seq : 0);

export type PendingKind = "confirmation" | "credential" | "question";
export interface Pending {
  kind: PendingKind;
  event: TaskEvent;
}

const REQUESTS: Record<string, PendingKind> = {
  confirmation_request: "confirmation",
  credential_request: "credential",
  question: "question",
};

/** What the agent is waiting on right now, if anything. */
export function pendingRequest(events: TaskEvent[], status: TaskStatus | undefined): Pending | null {
  if (status !== "awaiting_user") return null;
  for (let i = events.length - 1; i >= 0; i--) {
    const kind = REQUESTS[events[i].kind];
    if (kind) return { kind, event: events[i] };
    if (TERMINAL_EVENTS.has(events[i].kind)) return null;
  }
  return null;
}
