import type { BubbleProps } from "./types/index.ts";

// Unstyled chat bubble.
export function Bubble({ from, follow = false, ...rest }: BubbleProps) {
  return <div data-from={from} data-follow={follow || undefined} {...rest} />;
}
