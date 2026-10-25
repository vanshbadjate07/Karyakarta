import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Api } from "../lib/api";
import { ApiError } from "../lib/api";
import { pendingRequest } from "../lib/events";
import { duration, hostOf } from "../lib/format";
import { useTaskStream } from "../lib/hooks";
import { buildTimeline } from "../lib/timeline";
import { TERMINAL, type Shot, type Task } from "../lib/types";
import { IconRefresh, IconStop, IconTrash } from "./icons";
import { LivePanel } from "./LivePanel";
import { ConfirmationPrompt, CredentialPrompt, QuestionPrompt } from "./Prompts";
import { StatusBadge } from "./StatusBadge";
import { Timeline } from "./Timeline";

interface Props {
  api: Api;
  taskId: number;
  onChanged: () => void;
  onDeleted: () => void;
  onRerun: (task: Task) => void;
}

function useNow(active: boolean): number {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [active]);
  return now;
}

export function TaskView({ api, taskId, onChanged, onDeleted, onRerun }: Props) {
  const [task, setTask] = useState<Task | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [answered, setAnswered] = useState(0);
  const [selected, setSelected] = useState<number | null>(null);
  const [copied, setCopied] = useState(false);
  const { events } = useTaskStream(api, taskId);
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const load = useCallback(async () => {
    try {
      setTask(await api.getTask(taskId));
      setLoadError(null);
    } catch (e) {
      setLoadError(e instanceof ApiError ? e.message : "Could not load this task.");
    }
  }, [api, taskId]);

  useEffect(() => {
    setTask(null);
    setAnswered(0);
    setSelected(null);
    void load();
  }, [load]);

  // New activity means the task's status and steps may have changed: refresh shortly after.
  useEffect(() => {
    if (!events.length) return;
    clearTimeout(refreshTimer.current);
    refreshTimer.current = setTimeout(() => {
      void load();
      onChanged();
    }, 300);
    return () => clearTimeout(refreshTimer.current);
  }, [events.length, load, onChanged]);

  const timeline = useMemo(() => buildTimeline(events), [events]);
  const steps = task?.steps ?? [];
  const shots = useMemo(() => {
    const byIdx = new Map<number, Shot>();
    for (const s of steps) if (s.screenshot) byIdx.set(s.idx, { idx: s.idx, screenshot: s.screenshot, url: s.url });
    // A step waiting for approval has no saved row yet, but its picture is already known.
    for (const it of timeline.steps) if (it.screenshot && !byIdx.has(it.idx)) byIdx.set(it.idx, { idx: it.idx, screenshot: it.screenshot, url: it.url });
    return [...byIdx.values()].sort((a, b) => a.idx - b.idx);
  }, [steps, timeline.steps]);
  const pending = pendingRequest(events, task?.status);
  const showPending = pending && pending.event.seq > answered ? pending : null;
  const live = task ? !TERMINAL.has(task.status) : false;
  const now = useNow(live);

  const respond = (seq: number, call: Promise<unknown>) => call.then(() => setAnswered(seq));

  if (loadError && !task) return <div className="notice notice-bad">{loadError}</div>;
  if (!task) return <p className="empty">Loading...</p>;

  const seconds = task.started_at ? (task.finished_at ?? now / 1000) - task.started_at : 0;
  async function copyResult() {
    try {
      await navigator.clipboard.writeText(task?.result ?? "");
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable */
    }
  }

  return (
    <div className="work">
      <header className="topbar">
        <div className="topbar-main">
          <h2 title={task.instruction}>{task.instruction}</h2>
          <div className="meta">
            <StatusBadge status={task.status} />
            {task.start_url && <span>{hostOf(task.start_url)}</span>}
            {seconds > 0 && <span>{duration(seconds)}</span>}
            {steps.length > 0 && <span>{steps.length} steps</span>}
          </div>
        </div>
        <div className="topbar-actions">
          {live ? (
            <button className="btn btn-quiet-danger" onClick={() => void api.cancel(taskId).then(load)}>
              <IconStop size={12} /> Stop
            </button>
          ) : (
            <>
              <button className="btn" onClick={() => onRerun(task)}>
                <IconRefresh size={14} /> Run again
              </button>
              <button
                className="icon-btn"
                aria-label="Delete this task"
                title="Delete this task"
                onClick={() => {
                  if (window.confirm("Delete this task and its pictures?")) void api.remove(taskId).then(onDeleted);
                }}
              >
                <IconTrash size={15} />
              </button>
            </>
          )}
        </div>
      </header>

      <div className="work-grid">
        <Timeline
          instruction={task.instruction}
          startHost={hostOf(task.start_url)}
          items={timeline.steps}
          banners={timeline.banners}
          stepData={steps}
          selected={selected}
          live={live}
          onSelect={setSelected}
        >
          {showPending?.kind === "confirmation" && (
            <ConfirmationPrompt
              action={String(showPending.event.detail.action ?? showPending.event.message)}
              reasons={(showPending.event.detail.reasons as string[] | undefined) ?? []}
              onRespond={(approved) => respond(showPending.event.seq, api.confirm(taskId, approved))}
            />
          )}
          {showPending?.kind === "credential" && (
            <CredentialPrompt
              label={String(showPending.event.detail.label ?? "")}
              kind={String(showPending.event.detail.kind ?? "password")}
              onSubmit={(value) => respond(showPending.event.seq, api.sendCredential(taskId, value))}
              onCancel={() => void api.cancel(taskId).then(load)}
            />
          )}
          {showPending?.kind === "question" && (
            <QuestionPrompt question={showPending.event.message} onSubmit={(msg) => respond(showPending.event.seq, api.answer(taskId, msg))} />
          )}

          {task.status === "completed" && task.result && (
            <section className="result">
              <div className="result-head">
                <strong>Done</strong>
                <button className="link" onClick={() => void copyResult()}>
                  {copied ? "Copied" : "Copy"}
                </button>
              </div>
              <p>{task.result}</p>
            </section>
          )}
          {task.status === "failed" && task.error && (
            <section className="result result-bad">
              <div className="result-head">
                <strong>I could not finish this</strong>
              </div>
              <p>{task.error}</p>
            </section>
          )}
          {task.status === "cancelled" && <p className="working muted">You stopped this task.</p>}
        </Timeline>

        <LivePanel api={api} taskId={taskId} shots={shots} live={live} selected={selected} onSelect={setSelected} />
      </div>
    </div>
  );
}
