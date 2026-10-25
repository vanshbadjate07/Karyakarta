import { useState } from "react";
import type { Api } from "../lib/api";
import { openExternal } from "../lib/bridge";
import type { SystemStatus } from "../lib/types";
import { IconCheck, IconX } from "./icons";

interface Props {
  api: Api;
  status: SystemStatus | null;
  error: string | null;
  onRecheck: () => void;
}

function Row({ ok, title, children }: { ok: boolean; title: string; children: React.ReactNode }) {
  return (
    <li className="setup-row">
      <span className={ok ? "setup-mark setup-ok" : "setup-mark setup-todo"}>{ok ? <IconCheck size={14} /> : <IconX size={14} />}</span>
      <div>
        <h3>{title}</h3>
        <div className="setup-body">{children}</div>
      </div>
    </li>
  );
}

export function SetupScreen({ api, status, error, onRecheck }: Props) {
  const [progress, setProgress] = useState<number | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [pullError, setPullError] = useState<string | null>(null);

  async function download() {
    setDownloading(true);
    setPullError(null);
    setProgress(0);
    try {
      await api.pullModel((p) => setProgress(p.percent ?? null));
      onRecheck();
    } catch (e) {
      setPullError(e instanceof Error ? e.message : "The download failed.");
    } finally {
      setDownloading(false);
    }
  }

  if (!status) {
    return (
      <div className="setup">
        <h1>Setup</h1>
        <div className="notice notice-bad">
          <p>{error ?? "Checking your setup..."}</p>
          <button className="btn" onClick={onRecheck}>
            Check again
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="setup">
      <h1>Setup</h1>
      <p className="lead">Karyakarta runs entirely on this computer. Three things need to be in place.</p>
      <ul className="setup-list">
        <Row ok={status.engine_running} title="Local AI engine">
          {status.engine_running ? (
            <p>Running{status.engine_version ? ` (version ${status.engine_version})` : ""}.</p>
          ) : (
            <>
              <p>The engine that runs the AI model is not running. Install it, open it once, then check again.</p>
              <button className="btn" onClick={() => void openExternal("https://ollama.com/download")}>
                Get the engine
              </button>
            </>
          )}
        </Row>
        <Row ok={status.model_installed} title={`AI model (${status.model})`}>
          {status.model_installed ? (
            <p>Installed.</p>
          ) : (
            <>
              <p>A one-time download of about 2 GB. After that it works without internet for the AI part.</p>
              <button className="btn btn-primary" onClick={download} disabled={downloading || !status.engine_running}>
                {downloading ? "Downloading..." : "Download the model"}
              </button>
              {downloading && (
                <div className="progress" role="progressbar" aria-valuenow={progress ?? 0} aria-valuemin={0} aria-valuemax={100}>
                  <div className="progress-bar" style={{ width: `${progress ?? 0}%` }} />
                  <span>{progress === null ? "" : `${Math.round(progress)}%`}</span>
                </div>
              )}
              {pullError && <p className="form-error">{pullError}</p>}
              {!status.engine_running && <p className="hint">Start the engine first.</p>}
            </>
          )}
        </Row>
        <Row ok={status.browser_installed} title="Browser component">
          {status.browser_installed ? (
            <p>Installed.</p>
          ) : (
            <p>
              The browser Karyakarta controls is missing. In development, run <code>uv run playwright install chromium</code> in the Backend folder. The finished
              installer does this for you.
            </p>
          )}
        </Row>
      </ul>
      <button className="btn" onClick={onRecheck}>
        Check again
      </button>
    </div>
  );
}
