import { Callout as BaseCallout, cx } from "../base/index.ts";
import type { CalloutProps } from "./types/index.ts";
import "./styles/commonStyle.css";
import "./styles/Callout.css";

// Rounded block of small text set apart from what is around it.
export function Callout({ tone = "notice", className, ...rest }: CalloutProps) {
  return <BaseCallout tone={tone} className={cx("soft-block", "callout", className)} {...rest} />;
}
