import type { ReactNode } from "react";
import type { ClassNames } from "./commonType.ts";

export interface DescriptionItem {
  term: ReactNode;
  detail: ReactNode;
  key?: string;
}

export interface DescriptionListProps {
  items: DescriptionItem[];
  classNames?: ClassNames<"root" | "term" | "detail">;
}
