import { forwardRef } from "react";
import type { ButtonProps } from "./types/index.ts";

// Unstyled button. Defaults to type="button" so it never submits a form by accident.
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button({ type = "button", ...rest }, ref) {
  return <button ref={ref} type={type} {...rest} />;
});
