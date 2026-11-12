import type { HTMLAttributes } from "react";

export type StatusProps = HTMLAttributes<HTMLElement> & {
  inline?: boolean; // <span> instead of <div>
};
