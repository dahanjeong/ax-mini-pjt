import { forwardRef, type ButtonHTMLAttributes } from "react";

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement>;

// Unstyled button. Defaults to type="button" so it never submits a form by accident.
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button({ type = "button", ...rest }, ref) {
  return <button ref={ref} type={type} {...rest} />;
});
