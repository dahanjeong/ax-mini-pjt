import { Bubble as BaseBubble, cx, type BubbleProps as BaseBubbleProps } from "../base/index.ts";
import type { Role } from "../../types.ts";
import "./Bubble.css";

export interface BubbleProps extends BaseBubbleProps {
  from: Role;
}

// Chat bubble: user (dark, right), assistant (card, left), error (coral).
// A follow-up bubble is quieter than the first one of the turn.
export function Bubble({ from, follow = false, className, ...rest }: BubbleProps) {
  return <BaseBubble from={from} follow={follow} className={cx("bubble", from, follow && "follow", className)} {...rest} />;
}
