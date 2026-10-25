import { useEffect, useState, type FormEvent, type KeyboardEvent } from "react";
import type { Api } from "../lib/api";
import { ApiError } from "../lib/api";
import type { Task } from "../lib/types";
import { IconArrowUp, IconEye, IconGlobe, IconLock, IconShield } from "./icons";

const MODIFIER = /Mac|iPhone|iPad/.test(typeof navigator === "undefined" ? "" : navigator.platform) ? "Cmd" : "Ctrl";

const SUGGESTIONS = [
  { title: "Look something up", text: "Find the price of a product on a website and tell me" },
  { title: "Fill in a form", text: "Fill in the contact form with my name and email, then send it" },
  { title: "Research a topic", text: "Search this site for a topic and summarise the first result" },
];

interface Props {
  api: Api;
  ready: boolean | null;
  initial?: { instruction: string; startUrl: string };
  onCreated: (task: Task) => void;
  onOpenSetup: () => void;
}

export function TaskComposer({ api, ready, initial, onCreated, onOpenSetup }: Props) {
  const [instruction, setInstruction] = useState(initial?.instruction ?? "");
  const [startUrl, setStartUrl] = useState(initial?.startUrl ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setInstruction(initial?.instruction ?? "");
    setStartUrl(initial?.startUrl ?? "");
  }, [initial]);

  const valid = instruction.trim().length >= 3;

  async function submit(e?: FormEvent) {
    e?.preventDefault();
    if (!valid || busy || ready !== true) return;
    setBusy(true);
    setError(null);
    try {
      const task = await api.createTask(instruction.trim(), startUrl);
      setInstruction("");
      setStartUrl("");
      onCreated(task);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not start the task.");
    } finally {
      setBusy(false);
    }
  }

  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void submit();
  }

  return (
    <div className="home">
      <p className="eyebrow">Karyakarta</p>
      <h1 className="display">What shall I take care of?</h1>
      <p className="lead">Describe it in your own words. I will work in a real browser while you watch, and I will ask before anything that cannot be undone.</p>

      {ready === false && (
        <div className="notice notice-warn" role="status">
          <span>Setup is not finished, so tasks cannot start yet.</span>
          <button type="button" className="btn btn-sm" onClick={onOpenSetup}>
            Finish setup
          </button>
        </div>
      )}

      <form className="composer" onSubmit={submit}>
        <label htmlFor="instruction" className="sr-only">
          Task
        </label>
        <textarea
          id="instruction"
          className="composer-text"
          rows={3}
          maxLength={2000}
          autoFocus
          placeholder="For example: find the price of the book Dune on this site"
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
          onKeyDown={onKey}
        />
        <div className="composer-bar">
          <label className="site-field" htmlFor="start">
            <IconGlobe size={15} />
            <input
              id="start"
              placeholder="Start on a website (optional)"
              value={startUrl}
              onChange={(e) => setStartUrl(e.target.value)}
              inputMode="url"
              autoComplete="off"
              spellCheck={false}
            />
          </label>
          <span className="kbd-hint">
            <kbd>{MODIFIER}</kbd> <kbd>Enter</kbd>
          </span>
          <button className="send" type="submit" disabled={!valid || busy || ready !== true} aria-label="Start task">
            <IconArrowUp size={18} />
          </button>
        </div>
      </form>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}

      <div className="suggestions">
        {SUGGESTIONS.map((s) => (
          <button type="button" key={s.title} className="suggestion" onClick={() => setInstruction(s.text)}>
            <strong>{s.title}</strong>
            <span>{s.text}</span>
          </button>
        ))}
      </div>

      <ul className="pillars">
        <li>
          <IconEye size={16} /> Runs on this computer
        </li>
        <li>
          <IconShield size={16} /> Asks before anything risky
        </li>
        <li>
          <IconLock size={16} /> Never stores your passwords
        </li>
      </ul>
    </div>
  );
}
