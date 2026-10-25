import { useMemo } from "react";
import { groupByDay } from "../lib/groups";
import { timeAgo } from "../lib/format";
import type { Task, TaskStatus } from "../lib/types";
import { IconAlert, IconCheck, IconPlus, IconSpinner, IconX } from "./icons";

interface Props {
  tasks: Task[];
  selectedId: number | null;
  ready: boolean | null;
  error: string | null;
  onSelect: (id: number) => void;
  onNew: () => void;
  onSetup: () => void;
}

function StatusIcon({ status }: { status: TaskStatus }) {
  if (status === "running" || status === "queued") return <IconSpinner size={14} className="st st-run" />;
  if (status === "awaiting_user") return <IconAlert size={14} className="st st-wait" />;
  if (status === "completed") return <IconCheck size={14} className="st st-ok" />;
  if (status === "failed") return <IconX size={14} className="st st-bad" />;
  return <span className="st st-off" aria-hidden="true" />;
}

export function Sidebar({ tasks, selectedId, ready, error, onSelect, onNew, onSetup }: Props) {
  const groups = useMemo(() => groupByDay(tasks), [tasks]);
  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true">
          K
        </span>
        <span className="brand-name">Karyakarta</span>
      </div>

      <button className="new-task" onClick={onNew}>
        <IconPlus size={15} /> New task
      </button>

      <nav className="history" aria-label="Task history">
        {error && <p className="side-note">{error}</p>}
        {!error && tasks.length === 0 && <p className="side-note">Tasks you run will be kept here.</p>}
        {groups.map((g) => (
          <section key={g.label}>
            <h2>{g.label}</h2>
            <ul>
              {g.tasks.map((t) => (
                <li key={t.id}>
                  <button className={t.id === selectedId ? "h-item h-on" : "h-item"} onClick={() => onSelect(t.id)} title={t.instruction}>
                    <StatusIcon status={t.status} />
                    <span className="h-text">{t.instruction}</span>
                    <span className="h-time">{timeAgo(t.created_at)}</span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </nav>

      <div className="side-foot">
        <button className="ready" onClick={onSetup}>
          <span className={ready ? "dot dot-ok" : "dot dot-warn"} aria-hidden="true" />
          {ready === null ? "Checking" : ready ? "Ready" : "Setup needed"}
        </button>
      </div>
    </aside>
  );
}
