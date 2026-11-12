import type { HTMLAttributes } from "react";

export interface BubbleProps extends HTMLAttributes<HTMLDivElement> {
  from: string; // who said it, exposed as data-from
  follow?: boolean; // a follow-up bubble in the same turn, exposed as data-follow
}

// Unstyled chat bubble.
export function Bubble({ from, follow = false, ...rest }: BubbleProps) {
  return <div data-from={from} data-follow={follow || undefined} {...rest} />;
}
