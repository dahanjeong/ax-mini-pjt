import type { ChatState } from "./commonType.ts";

export type TopBarProps = Pick<ChatState, "online" | "canRestart"> & {
  onRestart: ChatState["restart"];
};
