// Calls to our own backend only (no external API, no keys in the frontend).
import type { ChatResponse } from "./types.ts";

export const API = "http://localhost:8000";

export class ChatError extends Error {}

export async function sendChat(message: string, sessionId: string | null): Promise<ChatResponse> {
  let res: Response;
  try {
    res = await fetch(`${API}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(sessionId ? { message, session_id: sessionId } : { message }),
    });
  } catch {
    throw new ChatError("서버에 연결할 수 없어요. 백엔드가 실행 중인지 확인해 주세요.");
  }
  if (res.status === 422) throw new ChatError("메시지는 1~500자로 입력해 주세요.");
  if (!res.ok) throw new ChatError("서버에서 문제가 생겼어요. 잠시 후 다시 시도해 주세요.");
  return (await res.json()) as ChatResponse;
}

export async function checkHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${API}/health`);
    return res.ok;
  } catch {
    return false;
  }
}
