import type { SendHandler } from "./commonType.ts";

export interface ExampleListProps {
  examples: string[];
  onPick: SendHandler;
}
