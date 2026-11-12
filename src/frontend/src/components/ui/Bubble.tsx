import { Bubble as BaseBubble, cx } from "../base/index.ts";
import type { BubbleProps } from "./types/index.ts";
import "./styles/commonStyle.css";
import "./styles/Bubble.css";

// Chat bubble: user (dark, right), assistant (card, left), error (coral).
// A follow-up bubble is quieter than the first one of the turn.
export function Bubble({ from, follow = false, className, ...rest }: BubbleProps) {
  return <BaseBubble from={from} follow={follow} className={cx("bubble", from, follow && "follow", className)} {...rest} />;
}
