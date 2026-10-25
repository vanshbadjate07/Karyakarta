import type { TaskStatus } from "./types";

export function timeAgo(tsSeconds: number, nowMs: number = Date.now()): string {
  const diff = Math.max(0, Math.round(nowMs / 1000 - tsSeconds));
  if (diff < 45) return "just now";
  if (diff < 3600) return `${Math.round(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)} h ago`;
  const days = Math.round(diff / 86400);
  return days === 1 ? "yesterday" : `${days} days ago`;
}

export function duration(seconds: number): string {
  if (seconds < 1) return "under a second";
  if (seconds < 60) return `${Math.round(seconds)} s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return s ? `${m} min ${s} s` : `${m} min`;
}

export const STATUS_LABEL: Record<TaskStatus, string> = {
  queued: "Waiting",
  running: "Working",
  awaiting_user: "Needs you",
  completed: "Finished",
  failed: "Failed",
  cancelled: "Cancelled",
};

export function hostOf(url: string | null | undefined): string {
  if (!url) return "";
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

export function formatBytes(percent: number | null): string {
  return percent === null ? "" : `${Math.round(percent)}%`;
}
