import type { Task } from "./types";

export interface TaskGroup {
  label: string;
  tasks: Task[];
}

/** Buckets history into Today, Yesterday and Earlier, newest first. */
export function groupByDay(tasks: Task[], nowMs: number = Date.now()): TaskGroup[] {
  const startOfToday = new Date(nowMs);
  startOfToday.setHours(0, 0, 0, 0);
  const today = startOfToday.getTime() / 1000;
  const yesterday = today - 86400;
  const buckets: Record<string, Task[]> = { Today: [], Yesterday: [], Earlier: [] };
  for (const t of tasks) {
    const key = t.created_at >= today ? "Today" : t.created_at >= yesterday ? "Yesterday" : "Earlier";
    buckets[key].push(t);
  }
  return Object.entries(buckets)
    .filter(([, list]) => list.length > 0)
    .map(([label, list]) => ({ label, tasks: list }));
}
