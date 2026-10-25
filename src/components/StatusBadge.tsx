import { STATUS_LABEL } from "../lib/format";
import type { TaskStatus } from "../lib/types";

export function StatusBadge({ status }: { status: TaskStatus }) {
  return (
    <span className={`badge badge-${status}`}>
      <span className="badge-dot" aria-hidden="true" />
      {STATUS_LABEL[status]}
    </span>
  );
}
