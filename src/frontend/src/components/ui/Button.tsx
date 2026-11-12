import { forwardRef } from "react";
import { Button as BaseButton, cx, type ButtonProps as BaseButtonProps } from "../base/index.ts";
import "./Button.css";

export interface ButtonProps extends BaseButtonProps {
  variant?: "stock" | "primary"; // stock: paper card; primary: the pear send action
  size?: "md" | "sm";
}

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
