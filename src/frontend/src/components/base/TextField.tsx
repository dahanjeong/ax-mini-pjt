import { forwardRef } from "react";
import type { TextFieldProps } from "./types/index.ts";

// Unstyled controlled text input that hands back the string, not the event.
export const TextField = forwardRef<HTMLInputElement, TextFieldProps>(function TextField(
  { value, onValueChange, type = "text", ...rest },
  ref,
) {
  return <input ref={ref} type={type} value={value} onChange={(e) => onValueChange(e.target.value)} {...rest} />;
});
