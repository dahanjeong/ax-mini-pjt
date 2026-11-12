import type { StatusProps } from "./types/index.ts";

// Unstyled polite live region: screen readers announce its text when it changes.
export function Status({ inline = false, ...rest }: StatusProps) {
  return inline ? <span role="status" {...rest} /> : <div role="status" {...rest} />;
}
