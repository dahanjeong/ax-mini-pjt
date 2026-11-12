import type { HTMLAttributes } from "react";

export interface StatusProps extends HTMLAttributes<HTMLElement> {
  inline?: boolean; // <span> instead of <div>
}

// Unstyled polite live region: screen readers announce its text when it changes.
export function Status({ inline = false, ...rest }: StatusProps) {
  return inline ? <span role="status" {...rest} /> : <div role="status" {...rest} />;
}
