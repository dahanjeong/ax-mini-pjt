import { LoadingDots } from "../base/index.ts";
import { Bubble } from "./Bubble.tsx";
import type { TypingIndicatorProps } from "./types/index.ts";
import "./styles/TypingIndicator.css"; // after Bubble.css: extends .bubble

// Assistant bubble with hopping dots, announced as a status while something is in progress.
// keep-motion: the dots still move (as a slow fade) under prefers-reduced-motion.
export function TypingIndicator({ children }: TypingIndicatorProps) {
  return (
    <Bubble from="assistant" role="status" className="pending">
      <LoadingDots className="dots keep-motion" dotClassName="keep-motion" />
      {children}
    </Bubble>
  );
}
