import type { DivProps } from "./commonType.ts";

export type BubbleProps = DivProps & {
  from: string; // who said it, exposed as data-from
  follow?: boolean; // a follow-up bubble in the same turn, exposed as data-follow
};
