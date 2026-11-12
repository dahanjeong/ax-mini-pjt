import type { HTMLAttributes } from "react";

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: string; // exposed as data-tone for the styled layer
}

// Unstyled inline label.
export function Badge({ tone, ...rest }: BadgeProps) {
  return <span data-tone={tone} {...rest} />;
}
