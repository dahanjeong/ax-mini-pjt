import { cx, Status, type StatusProps } from "../base/index.ts";
import "./StatusPill.css";

// Small coral pill that announces a status change (e.g. the server went offline).
export function StatusPill({ className, ...rest }: Omit<StatusProps, "inline">) {
  return <Status inline className={cx("status-pill", className)} {...rest} />;
}
