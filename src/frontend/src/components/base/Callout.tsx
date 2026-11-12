import type { HTMLAttributes } from "react";

export interface CalloutProps extends HTMLAttributes<HTMLDivElement> {
  tone?: string; // exposed as data-tone
}

// Unstyled block of text set apart from its surroundings (notice, warning).
export function Callout({ tone, ...rest }: CalloutProps) {
  return <div data-tone={tone} {...rest} />;
}
