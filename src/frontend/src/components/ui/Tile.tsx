import type { HTMLAttributes, ReactNode } from "react";
import { cx, Group } from "../base/index.ts";
import { Button, type ButtonProps } from "./Button.tsx";
import "./Tile.css";

export interface TileProps extends Omit<ButtonProps, "variant" | "size"> {
  variant?: "example" | "choice"; // example: thin tile; choice: tile with a numbered chip
  leading?: ReactNode; // shown in the numbered chip
}

// Full-width card-stock button holding a line of text, for picking one of several answers.
export function Tile({ variant = "choice", leading, className, children, ...rest }: TileProps) {
  return (
    <Button className={cx(variant, className)} {...rest}>
      {leading != null && <span className="num choice-n">{leading}</span>}
      <span className="tile-text">{children}</span>
    </Button>
  );
}

// Vertical stack of tiles.
export function TileGroup({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <Group className={cx("tile-group", className)} {...rest} />;
}
