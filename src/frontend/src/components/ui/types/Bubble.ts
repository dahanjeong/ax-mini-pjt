import type { BubbleProps as BaseBubbleProps } from "../../base/index.ts";

// who said it: user (dark, right), assistant (card, left), error (coral)
export type BubbleFrom = "user" | "assistant" | "error";

// the base takes any speaker; the styled bubble has a fixed set
export type BubbleProps = Omit<BaseBubbleProps, "from"> & { from: BubbleFrom };
