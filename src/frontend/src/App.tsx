import { useEffect, useRef, useState } from "react";
import PlaceCard from "./PlaceCard.tsx";
import { ChatError, checkHealth, sendChat } from "./api.ts";
import { toAssistantMessage } from "./format.ts";
import type { ChatMessage } from "./types.ts";

const EXAMPLES = [
  { text: "30개월 아기랑 이번 토요일에 강남역에서 출발해요" },
  { text: "18개월, 내일 판교역에서 실내 위주로 가고 싶어요" },
  { text: "24개월 아기, 모레 잠실역에서 서울숲 같은 곳" },
];
const WELCOME: ChatMessage = {
  role: "assistant",
  texts: ["안녕하세요! 오늘은 어디로 놀러 가볼까요? 🧺\n아기 월령, 출발지, 날짜를 알려주시면 아기와 함께 가기 좋은 곳 5곳을 찾아드려요."],
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
        <div className="brand">
          <h1>아기랑 나들이</h1>
          <p>우리 가족 주말 나들이, 같이 찾아봐요</p>
        </div>
        <div className="topbar-right">
          {!online && <span className="offline" role="status">서버 연결 안 됨</span>}
          <button type="button" className="stock small" onClick={restart} disabled={!sessionId || pending}>
            ↺ 처음부터
          </button>
        </div>
      </header>

      <main className="chat" aria-live="polite">
        {showExamples && <Hero />}
        {messages.map((m, i) => (
          <Message key={i} message={m} onChoose={send} disabled={pending} />
        ))}
        {showExamples && (
          <>
            <h2 className="examples-label" id="examples-label">이렇게 물어보세요</h2>
            <div className="examples" role="group" aria-labelledby="examples-label">
              {EXAMPLES.map((ex) => (
                <button type="button" key={ex.text} className="stock example" onClick={() => send(ex.text)}>
                  <span className="tile-text">{ex.text}</span>
                </button>
              ))}
            </div>
          </>
        )}
        {pending && (
          <div className="turn assistant">
            <div className="bubble assistant pending" role="status">
              <span className="dots keep-motion" aria-hidden="true"><i className="keep-motion" /><i className="keep-motion" /><i className="keep-motion" /></span>
              나들이 장소를 찾고 날씨·후기를 살펴보고 있어요. 10~20초쯤 걸려요.
            </div>
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
        <button type="submit" className="stock primary" disabled={pending || !input.trim()}>
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

function Hero() {
  return (
    <section className="hero" aria-label="소개">
      <h2>아기와 함께라면 어디든 소풍이에요</h2>
      <p>수유실·유모차 대여·주차부터 날씨와 미세먼지까지 한 번에 확인해 드릴게요.</p>
    </section>
  );
}

function Message({ message, onChoose, disabled }: MessageProps) {
  const { role, texts, notice, cards = [], choices = [] } = message;
  const bubbles = texts.map((t, i) => (
    <div key={i} className={`bubble ${role}${i > 0 ? " follow" : ""}`}>
      {t}
    </div>
  ));
  return (
    <div className={`turn ${role}`}>
      {bubbles}
      {notice && <div className="notice">{notice}</div>}
      {choices.length > 0 && (
        <div className="choices">
          {choices.map((c) => (
            <button type="button" key={c.send} className="stock choice" disabled={disabled} onClick={() => onChoose(c.send)}>
              <span className="num choice-n">{c.send}</span>
              <span className="tile-text">{c.label}</span>
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
