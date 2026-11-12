import { cx, DescriptionList, type DescriptionItem } from "../base/index.ts";
import "./DefinitionList.css";

export interface DefinitionListProps {
  items: DescriptionItem[];
  className?: string;
}

// Two-column term/detail rows split by hairlines.
export function DefinitionList({ items, className }: DefinitionListProps) {
  return <DescriptionList items={items} classNames={{ root: cx("def-list", className) }} />;
}
