import type { DivProps } from "./types/index.ts";

// Unstyled group of related controls (role="group"); name it with aria-label or aria-labelledby.
export function Group(props: DivProps) {
  return <div role="group" {...props} />;
}
