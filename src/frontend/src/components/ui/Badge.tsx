import { Badge as BaseBadge, cx } from "../base/index.ts";
import type { BadgeProps } from "./types/index.ts";
import "./styles/commonStyle.css";
import "./styles/Badge.css";

// Pill label.
export function Badge({ tone = "neutral", className, ...rest }: BadgeProps) {
  return <BaseBadge tone={tone} className={cx("pill", "badge", className)} {...rest} />;
}
