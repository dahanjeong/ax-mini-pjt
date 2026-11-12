import { Badge as BaseBadge, cx, type BadgeProps as BaseBadgeProps } from "../base/index.ts";
import "./Badge.css";

// good: mint · caution: sand · bad: coral · accent: pear · muted: quiet grey · neutral: paper
export type BadgeTone = "neutral" | "good" | "caution" | "bad" | "accent" | "muted";

export interface BadgeProps extends Omit<BaseBadgeProps, "tone"> {
  tone?: BadgeTone;
}

// Pill label.
export function Badge({ tone = "neutral", className, ...rest }: BadgeProps) {
  return <BaseBadge tone={tone} className={cx("badge", className)} {...rest} />;
}
