import type { CalloutProps } from "./types/index.ts";

// Unstyled block of text set apart from its surroundings (notice, warning); tone is exposed as data-tone.
export function Callout({ tone, ...rest }: CalloutProps) {
  return <div data-tone={tone} {...rest} />;
}
