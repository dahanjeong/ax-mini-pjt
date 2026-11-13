import { useEffect, useState } from "react";
import { CHAT_ERROR_MESSAGES, ChatError, checkHealth, sendChat } from "../../api/index.ts";
import { toAssistantMessage } from "./format.ts";
import type { ChatMessage } from "./types/index.ts";

const HEALTH_RECHECK_MS = 5_000;

// Transcript, session and server state of one chat, and the actions on it.
export function useChat(welcome: ChatMessage) {
  const [messages, setMessages] = useState<ChatMessage[]>([welcome]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [online, setOnline] = useState(true);

  useEffect(() => {
    checkHealth().then(setOnline);
  }, []);

  // While offline, check again every few seconds and when the tab comes back, so the
  // "연결 중…" pill clears by itself once the backend is up (started late, --reload restart).
  useEffect(() => {
    if (online) return;
    let cancelled = false;
    const recheck = () => {
      checkHealth().then((ok) => {
        if (!cancelled && ok) setOnline(true);
      });
    };
    const timer = window.setInterval(recheck, HEALTH_RECHECK_MS);
    const onVisible = () => {
      if (document.visibilityState === "visible") recheck();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [online]);

  // Ignored when empty or while an answer is still on its way.
  async function send(text: string) {
    const message = text.trim();
    if (!message || pending) return;
    setMessages((m) => [...m, { role: "user", texts: [message] }]);
    setPending(true);
    try {
      const view = await sendChat(message, sessionId);
      setSessionId(view.session_id);
      setOnline(true);
      setMessages((m) => [...m, toAssistantMessage(view)]);
    } catch (e) {
      const text = e instanceof ChatError ? e.message : "알 수 없는 오류가 생겼어요.";
      if (text === CHAT_ERROR_MESSAGES.unreachable) setOnline(false);   // starts the recheck above
      setMessages((m) => [...m, { role: "error", texts: [text] }]);
    } finally {
      setPending(false);
    }
  }

  function restart() {
    if (sessionId) send("처음부터 다시");
  }

  return { messages, pending, online, canRestart: sessionId !== null && !pending, send, restart };
}
