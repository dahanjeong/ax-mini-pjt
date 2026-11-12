import type { ButtonProps as BaseButtonProps } from "../../base/index.ts";
import type { Size } from "./commonType.ts";

export type ButtonVariant = "stock" | "primary"; // stock: paper card; primary: the pear send action

export type ButtonProps = BaseButtonProps & {
  variant?: ButtonVariant;
  size?: Size;
};
