import { useCallback, useEffect, useMemo, useState } from "react";
import { Api } from "./lib/api";
import { resolveConnection } from "./lib/bridge";
import { useSystemStatus, useTasks } from "./lib/hooks";
import type { Task } from "./lib/types";
import { Sidebar } from "./components/Sidebar";
import { SetupScreen } from "./components/SetupScreen";
import { TaskComposer } from "./components/TaskComposer";
import { TaskView } from "./components/TaskView";

type View = { kind: "new"; initial?: { instruction: string; startUrl: string } } | { kind: "task"; id: number } | { kind: "setup" };

export default function App() {
  const [api, setApi] = useState<Api | null>(null);
  const [startError, setStartError] = useState<string | null>(null);

  useEffect(() => {
    resolveConnection()
      .then((conn) => setApi(new Api(conn)))
      .catch((e: Error) => setStartError(e.message));
  }, []);

  if (startError) {
    return (
      <div className="boot">
        <h1>Karyakarta</h1>
        <p>{startError}</p>
      </div>
    );
  }
  if (!api) {
    return (
      <div className="boot">
        <h1>Karyakarta</h1>
        <p>Starting...</p>
      </div>
    );
  }
  return <Shell api={api} />;
}

function Shell({ api }: { api: Api }) {
  const { tasks, error: tasksError, refresh } = useTasks(api);
  const { status, error: statusError, refresh: refreshStatus } = useSystemStatus(api);
  const [view, setView] = useState<View>({ kind: "new" });

  const ready = status ? status.ready : null;
  const select = useCallback((id: number) => setView({ kind: "task", id }), []);
  const rerun = useCallback((t: Task) => setView({ kind: "new", initial: { instruction: t.instruction, startUrl: t.start_url ?? "" } }), []);

  const offline = useMemo(() => (statusError && !status ? statusError : null), [statusError, status]);

  return (
    <div className="app">
      <Sidebar
        tasks={tasks}
        selectedId={view.kind === "task" ? view.id : null}
        ready={ready}
        error={tasksError}
        onSelect={select}
        onNew={() => setView({ kind: "new" })}
        onSetup={() => setView({ kind: "setup" })}
      />
      <main className="main">
        {offline && <div className="notice notice-bad">{offline}</div>}
        {view.kind === "new" && (
          <TaskComposer
            api={api}
            ready={ready}
            initial={view.initial}
            onCreated={(t) => {
              void refresh();
              select(t.id);
            }}
            onOpenSetup={() => setView({ kind: "setup" })}
          />
        )}
        {view.kind === "task" && (
          <TaskView
            key={view.id}
            api={api}
            taskId={view.id}
            onChanged={() => void refresh()}
            onDeleted={() => {
              void refresh();
              setView({ kind: "new" });
            }}
            onRerun={rerun}
          />
        )}
        {view.kind === "setup" && <SetupScreen api={api} status={status} error={statusError} onRecheck={() => void refreshStatus()} />}
      </main>
    </div>
  );
}
