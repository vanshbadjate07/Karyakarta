import { useState, type FormEvent } from "react";
import { IconLock, IconShield } from "./icons";

interface ConfirmationProps {
  action: string;
  reasons: string[];
  onRespond: (approved: boolean) => Promise<void>;
}

/** The agent will not do this until the user says yes. */
export function ConfirmationPrompt({ action, reasons, onRespond }: ConfirmationProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function respond(approved: boolean) {
    setBusy(true);
    setError(null);
    try {
      await onRespond(approved);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not send your answer.");
      setBusy(false);
    }
  }

  return (
    <section className="prompt prompt-warn" role="alertdialog" aria-labelledby="confirm-title">
      <div className="prompt-head">
        <IconShield />
        <h3 id="confirm-title">Your approval is needed</h3>
      </div>
      <p className="prompt-action">{action}</p>
      {reasons.length > 0 && (
        <ul className="prompt-reasons">
          {reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      )}
      {error && <p className="prompt-error">{error}</p>}
      <div className="prompt-buttons">
        <button className="btn btn-primary" disabled={busy} onClick={() => respond(true)}>
          Approve
        </button>
        <button className="btn" disabled={busy} onClick={() => respond(false)}>
          Decline
        </button>
      </div>
    </section>
  );
}

interface CredentialProps {
  label: string;
  kind: string;
  onSubmit: (value: string) => Promise<void>;
  onCancel: () => void;
}

/** Secrets go straight to the website. The AI never sees them and nothing is saved. */
export function CredentialPrompt({ label, kind, onSubmit, onCancel }: CredentialProps) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const noun = kind === "password" ? "password" : kind === "code" ? "code" : "payment detail";

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!value || busy) return;
    setBusy(true);
    setError(null);
    const entered = value;
    setValue("");
    try {
      await onSubmit(entered);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send it.");
      setBusy(false);
    }
  }

  return (
    <form className="prompt prompt-secret" onSubmit={submit} aria-labelledby="secret-title">
      <div className="prompt-head">
        <IconLock />
        <h3 id="secret-title">Enter your {noun}</h3>
      </div>
      <p className="prompt-action">{label ? `The page asks for: ${label}` : `The page asks for a ${noun}.`}</p>
      <input
        className="input"
        type="password"
        autoComplete="off"
        autoCorrect="off"
        spellCheck={false}
        autoFocus
        aria-label={`Your ${noun}`}
        placeholder={`Your ${noun}`}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        disabled={busy}
      />
      <p className="prompt-note">
        It is typed straight into the website. Karyakarta never saves it and the AI never sees it.
      </p>
      {error && <p className="prompt-error">{error}</p>}
      <div className="prompt-buttons">
        <button className="btn btn-primary" type="submit" disabled={!value || busy}>
          Enter it
        </button>
        <button className="btn" type="button" onClick={onCancel} disabled={busy}>
          Cancel task
        </button>
      </div>
    </form>
  );
}

interface QuestionProps {
  question: string;
  onSubmit: (message: string) => Promise<void>;
}

export function QuestionPrompt({ question, onSubmit }: QuestionProps) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!value.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      await onSubmit(value.trim());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send your answer.");
      setBusy(false);
    }
  }

  return (
    <form className="prompt prompt-info" onSubmit={submit} aria-labelledby="question-title">
      <div className="prompt-head">
        <h3 id="question-title">The agent has a question</h3>
      </div>
      <p className="prompt-action">{question}</p>
      <input
        className="input"
        autoFocus
        aria-label="Your answer"
        placeholder="Type your answer"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        disabled={busy}
      />
      {error && <p className="prompt-error">{error}</p>}
      <div className="prompt-buttons">
        <button className="btn btn-primary" type="submit" disabled={!value.trim() || busy}>
          Send
        </button>
      </div>
    </form>
  );
}
