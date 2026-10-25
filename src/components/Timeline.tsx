import { useState, type ReactNode } from "react";
import type { Note, StepItem } from "../lib/timeline";
import type { Step } from "../lib/types";
import { hostOf } from "../lib/format";
import { IconAlert, IconCheck, IconChevron, IconSpinner, IconX } from "./icons";

function Node({ state }: { state: StepItem["state"] }) {
  if (state === "running") return <IconSpinner size={14} />;
  if (state === "ok") return <IconCheck size={13} />;
  if (state === "failed") return <IconX size={13} />;
  return <span className="node-dash" />;
}

function NoteLine({ note }: { note: Note }) {
  return (
    <p className={`note note-${note.tone}`}>
      <IconAlert size={13} />
      <span>{note.text}</span>
    </p>
  );
}

interface RowProps {
  item: StepItem;
  data?: Step;
  open: boolean;
  selected: boolean;
  onToggle: () => void;
}

function StepRow({ item, data, open, selected, onToggle }: RowProps) {
  const outcome = data?.detail?.outcome;
  return (
    <li className={`trow trow-${item.state}${selected ? " trow-sel" : ""}`}>
      <span className="trow-node" aria-hidden="true">
        <Node state={item.state} />
      </span>
      <div className="trow-main">
        <button className="trow-head" onClick={onToggle} aria-expanded={open}>
          <span className="trow-title">{item.title}</span>
          {item.result && !open && <span className="trow-result">{item.result}</span>}
          <IconChevron size={14} className={open ? "chev chev-open" : "chev"} />
        </button>
        {open && (
          <div className="trow-body">
            {item.thought && <p className="trow-thought">{item.thought}</p>}
            {item.result && <p className="trow-detail">{item.result}</p>}
            <div className="chips">
              {data && <span className={data.verified ? "tag tag-ok" : "tag"}>{data.verified ? "Verified" : outcome ?? "Checked"}</span>}
              {data?.url && <span className="tag">{hostOf(data.url)}</span>}
              {data?.model_ms ? <span className="tag">AI {(data.model_ms / 1000).toFixed(1)} s</span> : null}
            </div>
            {item.notes.map((n, i) => (
              <NoteLine key={i} note={n} />
            ))}
          </div>
        )}
        {!open && item.notes.length > 0 && item.notes.map((n, i) => <NoteLine key={i} note={n} />)}
      </div>
    </li>
  );
}

interface Props {
  instruction: string;
  startHost: string;
  items: StepItem[];
  banners: Note[];
  stepData: Step[];
  selected: number | null;
  live: boolean;
  onSelect: (idx: number) => void;
  children?: ReactNode;
}

export function Timeline({ instruction, startHost, items, banners, stepData, selected, live, onSelect, children }: Props) {
  const [opened, setOpened] = useState<Set<number>>(new Set());
  const lastIdx = items.length ? items[items.length - 1].idx : -1;

  function toggle(idx: number) {
    setOpened((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
    onSelect(idx);
  }

  return (
    <div className="timeline">
      <div className="ask">
        <p>{instruction}</p>
        {startHost && <span className="ask-site">{startHost}</span>}
      </div>

      {banners.map((b, i) => (
        <NoteLine key={i} note={b} />
      ))}

      {items.length === 0 && live && (
        <p className="working">
          <IconSpinner size={14} /> Getting started...
        </p>
      )}

      <ol className="steps">
        {items.map((it) => (
          <StepRow
            key={it.idx}
            item={it}
            data={stepData.find((s) => s.idx === it.idx)}
            open={opened.has(it.idx) || (live && it.idx === lastIdx)}
            selected={selected === it.idx}
            onToggle={() => toggle(it.idx)}
          />
        ))}
      </ol>
      {children}
    </div>
  );
}
