import { TERMINAL_EVENTS } from "./events";
import type { TaskEvent } from "./types";

export type StepState = "running" | "ok" | "failed" | "skipped";

export interface Note {
  tone: "warn" | "info";
  text: string;
}

export interface StepItem {
  idx: number;
  title: string;
  thought: string;
  result: string;
  state: StepState;
  notes: Note[];
  screenshot: string | null;
  url: string | null;
}

export interface Timeline {
  steps: StepItem[];
  /** Messages about the page or the task as a whole, not tied to one step. */
  banners: Note[];
}

/** Groups the raw activity stream into one tidy item per step. */
export function buildTimeline(events: TaskEvent[]): Timeline {
  const byStep = new Map<number, StepItem>();
  const banners: Note[] = [];

  const item = (n: number): StepItem => {
    let it = byStep.get(n);
    if (!it) {
      it = { idx: n, title: "", thought: "", result: "", state: "running", notes: [], screenshot: null, url: null };
      byStep.set(n, it);
    }
    return it;
  };

  for (const e of events) {
    const n = typeof e.detail?.step === "number" ? (e.detail.step as number) : null;
    switch (e.kind) {
      case "thought":
        if (n !== null) {
          const it = item(n);
          it.thought = e.message;
          if (typeof e.detail?.screenshot === "string" && e.detail.screenshot) it.screenshot = e.detail.screenshot;
          if (typeof e.detail?.url === "string") it.url = e.detail.url;
        }
        break;
      case "action":
        if (n !== null) {
          const it = item(n);
          it.title = e.message;
          it.state = "running";
        }
        break;
      case "confirmation_request":
      case "credential_request":
        if (n !== null) {
          const it = item(n);
          if (!it.title) it.title = String(e.detail?.action ?? e.message.replace(/^Karyakarta wants to: /, ""));
        }
        break;
      case "step_result":
        if (n !== null) {
          const it = item(n);
          it.result = e.message;
          it.state = e.detail?.ok === false ? "failed" : "ok";
        }
        break;
      case "policy":
        if (n !== null && e.detail?.decision && e.detail.decision !== "allow") {
          item(n).notes.push({ tone: "warn", text: e.message.replace(/^Safety check: /, "Safety check: ") });
        }
        break;
      case "warning":
      case "notice": {
        const note: Note = { tone: e.kind === "warning" ? "warn" : "info", text: e.message };
        if (n !== null) {
          const it = item(n);
          it.notes.push(note);
          if (!it.title && e.kind === "warning") it.state = "skipped";
        } else {
          banners.push(note);
        }
        break;
      }
    }
  }

  const steps = [...byStep.values()].sort((a, b) => a.idx - b.idx);
  const end = [...events].reverse().find((e) => TERMINAL_EVENTS.has(e.kind));
  for (const s of steps) {
    const closing = end && typeof end.detail?.steps === "number" && end.detail.steps === s.idx;
    if (!s.title && closing) {
      // The step where the agent concluded: it ends the task instead of acting on the page.
      s.title = end.kind === "task_complete" ? "Concluded the task" : "Stopped";
      s.state = end.kind === "task_complete" ? "ok" : "failed";
    } else if (end && s.state === "running") {
      s.state = "skipped"; // the task ended before this step could finish
    }
    if (!s.title) s.title = s.state === "skipped" ? "Reconsidering" : "Thinking";
  }
  return { steps, banners };
}
