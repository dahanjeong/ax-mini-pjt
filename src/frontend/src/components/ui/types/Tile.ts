import type { ReactNode } from "react";
import type { DivProps } from "../../base/index.ts";
import type { ButtonProps } from "./Button.ts";

export type TileVariant = "example" | "choice"; // example: thin tile; choice: tile with a numbered chip

// a tile is a stock button with its own variants and no size choice
export type TileProps = Omit<ButtonProps, "variant" | "size"> & {
  variant?: TileVariant;
  leading?: ReactNode; // shown in the numbered chip
};

export type TileGroupProps = DivProps;
