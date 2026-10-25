import { describe, expect, it } from "vitest";
import { lastSeq, mergeEvents, pendingRequest } from "../src/lib/events";
import { duration, hostOf, timeAgo } from "../src/lib/format";
import { groupByDay } from "../src/lib/groups";
import { buildTimeline } from "../src/lib/timeline";
import type { EventKind, Task, TaskEvent } from "../src/lib/types";

const ev = (seq: number, kind: EventKind, message = "", detail: Record<string, unknown> = {}): TaskEvent => ({ task_id: 1, seq, ts: seq, kind, message, detail });

describe("events", () => {
  it("merges without repeats, keeps order and drops pings", () => {
    const a = [ev(1, "task_started"), ev(2, "observe")];
    const merged = mergeEvents(a, [ev(2, "observe"), ev(3, "thought"), ev(9, "ping")]);
    expect(merged.map((e) => e.seq)).toEqual([1, 2, 3]);
    expect(lastSeq(merged)).toBe(3);
    expect(lastSeq([])).toBe(0);
  });

  it("finds what the agent is waiting for only while it is waiting", () => {
    const events = [ev(1, "thought"), ev(2, "credential_request", "Enter password")];
    expect(pendingRequest(events, "awaiting_user")?.kind).toBe("credential");
    expect(pendingRequest(events, "running")).toBeNull();
    expect(pendingRequest([...events, ev(3, "task_cancelled")], "awaiting_user")).toBeNull();
    expect(pendingRequest([ev(1, "confirmation_request"), ev(2, "question", "Which?")], "awaiting_user")?.kind).toBe("question");
  });
});

describe("timeline", () => {
  it("groups the raw stream into one item per step", () => {
    const t = buildTimeline([
      ev(1, "thought", "I see a form", { step: 1, screenshot: "1/step_01.jpg", url: "http://x/y" }),
      ev(2, "policy", "Safety check: allow", { step: 1, decision: "allow" }),
      ev(3, "action", 'Type "Asha" into "Name"', { step: 1 }),
      ev(4, "step_result", "Typed", { step: 1, ok: true }),
      ev(5, "thought", "Submit", { step: 2 }),
      ev(6, "policy", "Safety check: ask (submits a form)", { step: 2, decision: "ask" }),
      ev(7, "confirmation_request", "Karyakarta wants to: Click the button \"Send\"", { step: 2, action: 'Click the button "Send"' }),
      ev(8, "warning", "This page contains text that tries to give the agent instructions.", {}),
    ]);
    expect(t.steps).toHaveLength(2);
    expect(t.steps[0]).toMatchObject({ idx: 1, title: 'Type "Asha" into "Name"', state: "ok", result: "Typed", screenshot: "1/step_01.jpg", url: "http://x/y" });
    expect(t.steps[0].notes).toHaveLength(0); // routine "allow" checks stay out of the way
    expect(t.steps[1].title).toBe('Click the button "Send"');
    expect(t.steps[1].notes[0].text).toContain("ask");
    expect(t.banners).toHaveLength(1);
  });

  it("marks failed steps, rejected actions and the closing step", () => {
    const t = buildTimeline([
      ev(1, "thought", "x", { step: 1 }),
      ev(2, "warning", "Skipped an invalid action: bad mark", { step: 1 }),
      ev(3, "thought", "y", { step: 2 }),
      ev(4, "action", "Click the button \"Go\"", { step: 2 }),
      ev(5, "step_result", "Clicked but nothing happened", { step: 2, ok: false }),
      ev(6, "thought", "done", { step: 3 }),
      ev(7, "task_complete", "Price is $5", { steps: 3 }),
    ]);
    expect(t.steps.map((s) => s.state)).toEqual(["skipped", "failed", "ok"]);
    expect(t.steps[0].title).toBe("Reconsidering");
    expect(t.steps[2].title).toBe("Concluded the task");
  });

  it("settles a step that was still running when the task ended", () => {
    const t = buildTimeline([ev(1, "thought", "x", { step: 1 }), ev(2, "action", "Click the button \"Go\"", { step: 1 }), ev(3, "task_cancelled", "Task cancelled.")]);
    expect(t.steps[0].state).toBe("skipped");
  });
});

describe("history grouping and wording", () => {
  const task = (id: number, created: number): Task => ({ id, instruction: "t", start_url: null, status: "completed", result: null, error: null, model: null, created_at: created, started_at: null, finished_at: null });
  it("buckets by day", () => {
    const now = new Date(2026, 9, 25, 15, 0, 0).getTime();
    const s = now / 1000;
    const groups = groupByDay([task(3, s - 60), task(2, s - 86400 + 3600 * 5 - 3600 * 15), task(1, s - 86400 * 5)], now);
    expect(groups.map((g) => g.label)).toEqual(["Today", "Yesterday", "Earlier"]);
    expect(groupByDay([], now)).toEqual([]);
  });
  it("formats time, duration and hosts", () => {
    const now = 1_000_000_000_000;
    expect(timeAgo(now / 1000 - 10, now)).toBe("just now");
    expect(timeAgo(now / 1000 - 600, now)).toBe("10 min ago");
    expect(timeAgo(now / 1000 - 7200, now)).toBe("2 h ago");
    expect(timeAgo(now / 1000 - 86400 * 3, now)).toBe("3 days ago");
    expect(duration(0.2)).toBe("under a second");
    expect(duration(75)).toBe("1 min 15 s");
    expect(hostOf("http://127.0.0.1:8801/a")).toBe("127.0.0.1:8801");
    expect(hostOf(null)).toBe("");
  });
});
