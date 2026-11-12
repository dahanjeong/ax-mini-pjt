import type { ReactNode } from "react";
import { LoadingDots } from "../base/index.ts";
import { Bubble } from "./Bubble.tsx";
import "./TypingIndicator.css";

// Assistant bubble with hopping dots, announced as a status while something is in progress.
// keep-motion: the dots still move (as a slow fade) under prefers-reduced-motion.
export function TypingIndicator({ children }: { children: ReactNode }) {
  return (
    <Bubble from="assistant" role="status" className="pending">
      <LoadingDots className="dots keep-motion" dotClassName="keep-motion" />
      {children}
    </Bubble>
  );
}
