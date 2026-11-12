import type { SourceLink } from "./format.ts";

// already filtered to safe links by sourceLinks()
export interface ReviewSourcesProps {
  sources: SourceLink[];
}
