import type { BadgeProps } from "./types/index.ts";

// Unstyled inline label; tone is exposed as data-tone.
export function Badge({ tone, ...rest }: BadgeProps) {
  return <span data-tone={tone} {...rest} />;
}
