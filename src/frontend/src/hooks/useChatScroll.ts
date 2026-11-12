import { useEffect, type RefObject } from "react";

interface Options {
  count: number; // messages in the transcript
  pending: boolean;
  pendingRef: RefObject<HTMLElement | null>;
  lastTurnRef: RefObject<HTMLElement | null>;
}

// While waiting, keep the "working on it" bubble in sight above the sticky composer;
// when the answer arrives, scroll to where it starts (not past its cards to the end).
// The welcome screen (one message, nothing pending) stays at the top.
export function useChatScroll({ count, pending, pendingRef, lastTurnRef }: Options) {
  useEffect(() => {
    if (count === 1 && !pending) return;
    const frame = requestAnimationFrame(() => {
      const behavior: ScrollBehavior = window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "auto"
        : "smooth";
      if (pending) {
        pendingRef.current?.scrollIntoView({ behavior, block: "end" });
      } else {
        lastTurnRef.current?.scrollIntoView({ behavior, block: "start" });
      }
    });
    return () => cancelAnimationFrame(frame);
  }, [count, pending, pendingRef, lastTurnRef]);
}
