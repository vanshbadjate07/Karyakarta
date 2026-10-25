import { useCallback, useEffect, useRef, useState } from "react";
import type { Api } from "./api";
import { ApiError } from "./api";
import { TERMINAL_EVENTS, lastSeq, mergeEvents } from "./events";
import { TERMINAL, type SystemStatus, type Task, type TaskEvent } from "./types";

/** Live activity for one task: a WebSocket that reconnects, and falls back to polling. */
export function useTaskStream(api: Api, taskId: number) {
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const [finished, setFinished] = useState(false);

  useEffect(() => {
    let closed = false;
    let ended = false;
    let socket: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let failures = 0;
    let latest = 0;
    setEvents([]);
    setFinished(false);

    const take = (incoming: TaskEvent[]) => {
      if (!incoming.length) return;
      setEvents((prev) => {
        const merged = mergeEvents(prev, incoming);
        latest = lastSeq(merged);
        return merged;
      });
      if (incoming.some((e) => TERMINAL_EVENTS.has(e.kind))) {
        ended = true;
        setFinished(true);
      }
    };

    const poll = async () => {
      if (closed || ended) return;
      try {
        take(await api.getEvents(taskId, latest));
      } catch {
        /* keep trying */
      }
      if (!closed && !ended) timer = setTimeout(poll, 2000);
    };

    const connect = () => {
      if (closed || ended) return;
      let opened = false;
      try {
        socket = new WebSocket(api.streamUrl(taskId, latest));
      } catch {
        void poll();
        return;
      }
      socket.onopen = () => {
        opened = true;
        failures = 0;
      };
      socket.onmessage = (msg) => {
        try {
          take([JSON.parse(msg.data) as TaskEvent]);
        } catch {
          /* ignore a malformed frame */
        }
      };
      socket.onclose = () => {
        if (closed || ended) return;
        if (!opened) failures += 1;
        if (failures >= 3) {
          void poll();
          return;
        }
        timer = setTimeout(connect, Math.min(1000 * 2 ** failures, 8000));
      };
    };

    connect();
    return () => {
      closed = true;
      if (timer) clearTimeout(timer);
      socket?.close();
    };
  }, [api, taskId]);

  return { events, finished };
}

export function useTasks(api: Api) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [error, setError] = useState<string | null>(null);
  const active = useRef(false);

  const refresh = useCallback(async () => {
    try {
      const list = await api.listTasks();
      active.current = list.some((t) => !TERMINAL.has(t.status));
      setTasks(list);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load your tasks.");
    }
  }, [api]);

  useEffect(() => {
    let stop = false;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      await refresh();
      if (!stop) timer = setTimeout(tick, active.current ? 3000 : 15000);
    };
    void tick();
    return () => {
      stop = true;
      clearTimeout(timer);
    };
  }, [refresh]);

  return { tasks, error, refresh };
}

export function useSystemStatus(api: Api) {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setStatus(await api.status());
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Cannot reach the Karyakarta service.");
    }
  }, [api]);

  useEffect(() => {
    let stop = false;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      await refresh();
      if (!stop) timer = setTimeout(tick, 6000);
    };
    void tick();
    return () => {
      stop = true;
      clearTimeout(timer);
    };
  }, [refresh]);

  return { status, error, refresh };
}

/** Screenshots need the access token, so they are fetched and shown from memory. */
export function useScreenshot(api: Api, taskId: number, path: string | null) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!path) return;
    let revoked = false;
    let objectUrl: string | null = null;
    api
      .screenshot(taskId, path)
      .then((blob) => {
        if (revoked) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch(() => setUrl(null));
    return () => {
      revoked = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [api, taskId, path]);
  return url;
}
