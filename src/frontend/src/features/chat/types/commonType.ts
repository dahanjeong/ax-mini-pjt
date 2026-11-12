// Shapes shared by the chat feature.
import type { PlaceCardData } from "../../../api/index.ts";
import type { BubbleFrom } from "../../../components/ui/index.ts";
import type { useChat } from "../useChat.ts";

// Sends a line of text as the user's message (composer, example tiles, choice tiles).
export type SendHandler = (text: string) => void;

// What useChat hands to the screen.
export type ChatState = ReturnType<typeof useChat>;

// ---- the transcript ----

// who said it; each role is drawn as its own kind of bubble
export type Role = BubbleFrom;

// a numbered answer the user can pick instead of typing
export interface Choice {
  label: string;
  send: string; // what is sent when picked ("1", "2", …)
}

// one entry of the transcript
export interface ChatMessage {
  role: Role;
  texts: string[];
  notice?: string | null;
  cards?: PlaceCardData[];
  choices?: Choice[];
}
