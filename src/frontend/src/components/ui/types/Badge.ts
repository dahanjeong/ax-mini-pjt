import type { BadgeProps as BaseBadgeProps } from "../../base/index.ts";
import type { StatusTone, WithTone } from "./commonType.ts";

// accent: pear · muted: quiet grey · neutral: paper
export type BadgeTone = "neutral" | StatusTone | "accent" | "muted";

export type BadgeProps = WithTone<BaseBadgeProps, BadgeTone>;
