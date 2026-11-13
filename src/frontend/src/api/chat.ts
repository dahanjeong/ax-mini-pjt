// Domain layer: the chat backend's endpoints, and what to tell the user when they fail.
import type { ChatResponse } from "./types/index.ts";
import { get, HttpError, post } from "./http/index.ts";

export class ChatError extends Error {}

export const CHAT_ERROR_MESSAGES = {
  unreachable: "지금은 나들이 도우미와 연결이 잠시 끊겼어요. 잠시 후 다시 보내 주세요.",
  invalid: "메시지는 1~500자로 입력해 주세요.",
  server: "답을 준비하다가 문제가 생겼어요. 잠시 후 다시 보내 주세요.",
} as const;

interface ChatRequest {
  message: string;
  session_id?: string;
}

// HttpError -> the sentence shown in the error bubble.
// A timeout means the server took the request but did not answer in time: the server message.
export function chatErrorMessage(error: unknown): string {
  const e = HttpError.from(error);
  if (e.kind === "network") return CHAT_ERROR_MESSAGES.unreachable;
  if (e.status === 422) return CHAT_ERROR_MESSAGES.invalid;
  return CHAT_ERROR_MESSAGES.server;
}

export async function sendChat(message: string, sessionId: string | null): Promise<ChatResponse> {
  const body: ChatRequest = sessionId ? { message, session_id: sessionId } : { message };
  try {
    return await post<ChatResponse, ChatRequest>("/chat", body);
  } catch (e) {
    throw new ChatError(chatErrorMessage(e));
  }
}

// true when the backend answers /health; never throws
export async function checkHealth(): Promise<boolean> {
  try {
    await get<unknown>("/health");
    return true;
  } catch {
    return false;
  }
}
