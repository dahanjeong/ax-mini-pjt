import { useEffect, useRef, useState } from "react";
import PlaceCard from "./PlaceCard.tsx";
import { ChatError, checkHealth, sendChat } from "./api.ts";
import { toAssistantMessage } from "./format.ts";
import type { ChatMessage } from "./types.ts";

const EXAMPLES = [
  { icon: "🌳", text: "30개월 아기랑 이번 토요일에 강남역에서 출발해요" },
  { icon: "🏠", text: "18개월, 내일 판교역에서 실내 위주로 가고 싶어요" },
  { icon: "🌷", text: "24개월 아기, 모레 잠실역에서 서울숲 같은 곳" },
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
          <span className="brand-logo" aria-hidden="true">🧸</span>
          <div>
            <h1>아기랑 나들이</h1>
            <p>우리 가족 주말 나들이, 같이 찾아봐요</p>
          </div>
        </div>
        <div className="topbar-right">
          {!online && <span className="offline">서버 연결 안 됨</span>}
          <button type="button" className="ghost" onClick={restart} disabled={!sessionId || pending}>
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
            <p className="examples-label">이렇게 물어보세요</p>
            <div className="examples">
              {EXAMPLES.map((ex) => (
                <button type="button" key={ex.text} className="chip" onClick={() => send(ex.text)}>
                  <span aria-hidden="true">{ex.icon}</span> {ex.text}
                </button>
              ))}
            </div>
          </>
        )}
        {pending && (
          <div className="turn assistant">
            <div className="turn-row">
              <Avatar />
              <div className="turn-body">
                <div className="bubble assistant pending">
                  <span className="dots" aria-hidden="true"><i /><i /><i /></span>
                  나들이 장소를 찾고 날씨·후기를 살펴보고 있어요. 10~20초쯤 걸려요.
                </div>
              </div>
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

function Avatar() {
  return (
    <span className="avatar" aria-hidden="true">
      🐣
    </span>
  );
}

function Hero() {
  return (
    <section className="hero" aria-label="소개">
      <svg viewBox="0 0 320 120" role="img" aria-label="해가 뜬 언덕 풍경">
        <circle cx="262" cy="34" r="20" fill="#ffd166" />
        <g stroke="#ffd166" strokeWidth="3" strokeLinecap="round">
          <line x1="262" y1="4" x2="262" y2="9" />
          <line x1="292" y1="34" x2="287" y2="34" />
          <line x1="283" y1="13" x2="280" y2="16" />
          <line x1="241" y1="13" x2="244" y2="16" />
          <line x1="283" y1="55" x2="280" y2="52" />
        </g>
        <g fill="#ffffff" stroke="#f1dfcc" strokeWidth="1.5">
          <ellipse cx="70" cy="30" rx="26" ry="11" />
          <ellipse cx="88" cy="24" rx="16" ry="10" />
          <ellipse cx="170" cy="44" rx="20" ry="8" />
        </g>
        <path d="M0 96 Q70 56 150 88 T320 78 V120 H0Z" fill="#cfe5c3" />
        <path d="M0 108 Q90 80 190 104 T320 98 V120 H0Z" fill="#a9d18e" />
        <g transform="translate(60 74)">
          <rect x="-2" y="0" width="4" height="22" fill="#a07850" />
          <circle cx="0" cy="-4" r="13" fill="#7fb069" />
        </g>
        <g transform="translate(150 78)">
          <path d="M0 0 h22 a12 12 0 0 1 -12 12 h-10z" fill="#e8775a" />
          <path d="M0 0 a12 12 0 0 1 12 -12 v12z" fill="#c4553b" />
          <line x1="22" y1="0" x2="30" y2="-8" stroke="#3d2c23" strokeWidth="2" strokeLinecap="round" />
          <circle cx="3" cy="16" r="3.5" fill="#3d2c23" />
          <circle cx="19" cy="16" r="3.5" fill="#3d2c23" />
        </g>
        <g fill="#ffffff">
          <circle cx="110" cy="104" r="3" /><circle cx="230" cy="100" r="3" /><circle cx="280" cy="108" r="3" />
        </g>
        <g fill="#ffd166">
          <circle cx="110" cy="104" r="1.2" /><circle cx="230" cy="100" r="1.2" /><circle cx="280" cy="108" r="1.2" />
        </g>
      </svg>
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
      {role === "user" ? (
        bubbles
      ) : (
        <div className="turn-row">
          <Avatar />
          <div className="turn-body">{bubbles}</div>
        </div>
      )}
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
