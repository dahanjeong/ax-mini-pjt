import { cx, Group } from "../base/index.ts";
import { Button } from "./Button.tsx";
import type { TileGroupProps, TileProps } from "./types/index.ts";
import "./styles/Tile.css"; // after Button.css: overrides .stock padding and edge

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
export function TileGroup({ className, ...rest }: TileGroupProps) {
  return <Group className={cx("tile-group", className)} {...rest} />;
}
