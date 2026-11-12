// Pure helpers that turn backend answers into transcript entries (tested with `npm test`).
import type { ChatResponse } from "../../api/index.ts";
import type { ChatMessage, Choice } from "./types/index.ts";

// One /chat response -> one assistant message for the transcript.
export function toAssistantMessage(view: ChatResponse): ChatMessage {
  const texts = view.messages && view.messages.length ? view.messages : view.reply ? [view.reply] : [];
  const pool = view.reference_candidates && view.reference_candidates.length
    ? view.reference_candidates
    : view.candidates || [];
  const choices: Choice[] = pool.map((c, i) => ({
    label: c.address ? `${c.name} (${c.address})` : c.name,
    send: String(i + 1),
  }));
  // the backend often repeats the notice at the start of the reply: show it only once
  const notice = view.notice && !texts.some((t) => t.includes(view.notice as string)) ? view.notice : null;
  return {
    role: "assistant",
    texts,
    notice,
    cards: view.result_cards || [],
    choices: view.status === "ask" ? choices : [],
  };
}
