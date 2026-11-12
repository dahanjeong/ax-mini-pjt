import { forwardRef } from "react";
import { Button as BaseButton, cx } from "../base/index.ts";
import type { ButtonProps } from "./types/index.ts";
import "./styles/Button.css";

// Card-stock button that lifts on hover and presses down on click.
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "stock", size = "md", className, ...rest },
  ref,
) {
  return (
    <BaseButton
      ref={ref}
      className={cx("stock", variant === "primary" && "primary", size === "sm" && "small", className)}
      {...rest}
    />
  );
});
