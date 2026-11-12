import { Callout as BaseCallout, cx, type CalloutProps as BaseCalloutProps } from "../base/index.ts";
import "./Callout.css";

export interface CalloutProps extends Omit<BaseCalloutProps, "tone"> {
  tone?: "notice" | "warning"; // notice: sand, for information; warning: coral, for caution
}

// Rounded block of small text set apart from what is around it.
export function Callout({ tone = "notice", className, ...rest }: CalloutProps) {
  return <BaseCallout tone={tone} className={cx("callout", className)} {...rest} />;
}
