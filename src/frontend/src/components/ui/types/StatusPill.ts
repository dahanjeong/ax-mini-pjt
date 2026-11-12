import type { StatusProps } from "../../base/index.ts";

// always inline
export type StatusPillProps = Omit<StatusProps, "inline">;
