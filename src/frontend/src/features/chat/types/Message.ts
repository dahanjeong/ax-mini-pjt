import type { Ref } from "react";
import type { ChatState, SendHandler } from "./commonType.ts";

export interface MessageProps {
  message: ChatState["messages"][number];
  onChoose: SendHandler;
  disabled: boolean; // choices can't be picked while an answer is on its way
  turnRef?: Ref<HTMLDivElement>;
}
