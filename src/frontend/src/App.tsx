import { useEffect, useRef, useState } from "react";
import PlaceCard from "./PlaceCard.tsx";
import { ChatError, checkHealth, sendChat } from "./api.ts";
import { toAssistantMessage } from "./format.ts";
import type { ChatMessage } from "./types.ts";

const EXAMPLES = [
  "30개월 아기랑 이번 토요일에 강남역에서 출발해요",
  "18개월, 내일 판교역에서 실내 위주로 가고 싶어요",
  "24개월 아기, 모레 잠실역에서 서울숲 같은 곳",
];
const WELCOME: ChatMessage = {
  role: "assistant",
  texts: ["안녕하세요! 아기 월령, 출발지, 날짜를 알려주시면 아기와 함께 가기 좋은 곳 5곳을 찾아드려요."],
  cards: [],
  choices: [],
};

export default function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([WELCOME]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(false);
  const [online, setOnline] = useState(true);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    checkHealth().then(setOnline);
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, pending]);

  async function send(text: string) {
    const message = text.trim();
    if (!message || pending) return;
    setMessages((m) => [...m, { role: "user", texts: [message] }]);
    setInput("");
    setPending(true);
    try {
      const view = await sendChat(message, sessionId);
      setSessionId(view.session_id);
      setOnline(true);
      setMessages((m) => [...m, toAssistantMessage(view)]);
    } catch (e) {
      const text = e instanceof ChatError ? e.message : "알 수 없는 오류가 생겼어요.";
      setMessages((m) => [...m, { role: "error", texts: [text] }]);
    } finally {
      setPending(false);
    }
  }

  function restart() {
    if (sessionId) send("처음부터 다시");
  }

  const showExamples = messages.length === 1 && !pending;

  return (
    <div className="app">
      <header className="topbar">
        <h1>아기랑 나들이</h1>
        <div className="topbar-right">
          {!online && <span className="offline">서버 연결 안 됨</span>}
          <button type="button" className="ghost" onClick={restart} disabled={!sessionId || pending}>
            처음부터
          </button>
        </div>
      </header>

      <main className="chat" aria-live="polite">
        {messages.map((m, i) => (
          <Message key={i} message={m} onChoose={send} disabled={pending} />
        ))}
        {showExamples && (
          <div className="examples">
            {EXAMPLES.map((ex) => (
              <button type="button" key={ex} className="chip" onClick={() => send(ex)}>
                {ex}
              </button>
            ))}
          </div>
        )}
        {pending && (
          <div className="bubble assistant pending">
            <span className="dots" aria-hidden="true" />
            장소를 찾고 날씨·후기를 확인하고 있어요. 추천은 10~20초쯤 걸려요.
          </div>
        )}
        <div ref={endRef} />
      </main>

      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="예: 30개월 아기랑 이번 토요일에 강남역에서 출발해요"
          maxLength={500}
          disabled={pending}
          aria-label="메시지"
        />
        <button type="submit" disabled={pending || !input.trim()}>
          보내기
        </button>
      </form>
    </div>
  );
}

interface MessageProps {
  message: ChatMessage;
  onChoose: (text: string) => void;
  disabled: boolean;
}

function Message({ message, onChoose, disabled }: MessageProps) {
  const { role, texts, notice, cards = [], choices = [] } = message;
  return (
    <div className={`turn ${role}`}>
      {texts.map((t, i) => (
        <div key={i} className={`bubble ${role}${i > 0 ? " follow" : ""}`}>
          {t}
        </div>
      ))}
      {notice && <div className="notice">{notice}</div>}
      {choices.length > 0 && (
        <div className="choices">
          {choices.map((c) => (
            <button type="button" key={c.send} className="chip" disabled={disabled} onClick={() => onChoose(c.send)}>
              {c.send}. {c.label}
            </button>
          ))}
        </div>
      )}
      {cards.length > 0 && (
        <div className="cards">
          {cards.map((card, i) => (
            <PlaceCard key={`${card.name}-${i}`} card={card} rank={i + 1} />
          ))}
        </div>
      )}
    </div>
  );
}
