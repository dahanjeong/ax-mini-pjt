import { cx, Status } from "../base/index.ts";
import type { StatusPillProps } from "./types/index.ts";
import "./styles/commonStyle.css";
import "./styles/StatusPill.css";

// Small coral pill that announces a status change (e.g. the server went offline).
export function StatusPill({ className, ...rest }: StatusPillProps) {
  return <Status inline className={cx("pill", "status-pill", className)} {...rest} />;
}
