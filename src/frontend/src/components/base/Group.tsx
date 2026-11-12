import type { HTMLAttributes } from "react";

// Unstyled group of related controls (role="group"); name it with aria-label or aria-labelledby.
export function Group(props: HTMLAttributes<HTMLDivElement>) {
  return <div role="group" {...props} />;
}
