import { cx, DescriptionList } from "../base/index.ts";
import type { DefinitionListProps } from "./types/index.ts";
import "./styles/DefinitionList.css";

// Two-column term/detail rows split by hairlines.
export function DefinitionList({ className, ...rest }: DefinitionListProps) {
  return <DescriptionList {...rest} classNames={{ root: cx("def-list", className) }} />;
}
