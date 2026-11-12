import { useEffect, useRef, type RefObject } from "react";

// Moves focus to `target` when `busy` turns from true to false, e.g. back into the composer
// once an answer arrives so a follow-up question can be typed right away.
// preventScroll: scrolling is left to whoever positions the page.
export function useFocusWhenSettled(busy: boolean, target: RefObject<HTMLElement | null>) {
  const wasBusy = useRef(false);
  useEffect(() => {
    if (wasBusy.current && !busy) target.current?.focus({ preventScroll: true });
    wasBusy.current = busy;
  }, [busy, target]);
}
