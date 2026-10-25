import { useEffect, useState } from "react";
import type { Api } from "../lib/api";
import { hostOf } from "../lib/format";
import { useScreenshot } from "../lib/hooks";
import type { Shot } from "../lib/types";
import { IconChevron, IconEye } from "./icons";

interface Props {
  api: Api;
  taskId: number;
  shots: Shot[];
  live: boolean;
  selected: number | null;
  onSelect: (idx: number | null) => void;
}

export function LivePanel({ api, taskId, shots: withShots, live, selected, onSelect }: Props) {
  const [zoom, setZoom] = useState(false);
  const current = (selected !== null && withShots.find((s) => s.idx === selected)) || withShots[withShots.length - 1];
  const url = useScreenshot(api, taskId, current?.screenshot ?? null);
  const position = current ? withShots.indexOf(current) : -1;
  const following = selected === null;

  useEffect(() => {
    if (!zoom) return;
    const close = (e: KeyboardEvent) => e.key === "Escape" && setZoom(false);
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [zoom]);

  const go = (delta: number) => {
    const target = withShots[position + delta];
    if (target) onSelect(target.idx);
  };

  return (
    <aside className="live" aria-label="Live view">
      <div className="live-head">
        <span className="live-title">
          <IconEye size={15} /> {live && following ? "Live view" : "Replay"}
        </span>
        {live && !following && (
          <button className="link" onClick={() => onSelect(null)}>
            Follow live
          </button>
        )}
      </div>

      <div className="browser">
        <div className="browser-bar">
          <span className="lights" aria-hidden="true">
            <i />
            <i />
            <i />
          </span>
          <span className="address">{current ? hostOf(current.url) || "page" : "waiting for a page"}</span>
        </div>
        <button className="browser-view" onClick={() => url && setZoom(true)} disabled={!url} aria-label="Enlarge the page picture">
          {url ? <img src={url} alt={`The page at step ${current?.idx}`} /> : <span className={current ? "skeleton" : "browser-empty"}>{current ? "" : "The browser appears here once the agent starts."}</span>}
        </button>
      </div>

      {current && (
        <div className="scrub">
          <button className="icon-btn flip" onClick={() => go(-1)} disabled={position <= 0} aria-label="Previous step">
            <IconChevron size={16} />
          </button>
          <span>
            Step {current.idx} <em>of {withShots.length}</em>
          </span>
          <button className="icon-btn" onClick={() => go(1)} disabled={position >= withShots.length - 1} aria-label="Next step">
            <IconChevron size={16} />
          </button>
        </div>
      )}
      {current && <p className="live-caption">What the agent saw before it acted.</p>}

      {zoom && url && (
        <div className="lightbox" role="dialog" aria-label="Page picture" onClick={() => setZoom(false)}>
          <img src={url} alt="Full page picture" />
        </div>
      )}
    </aside>
  );
}
