import { useEffect, useRef, useState, type Ref } from "react";
import PlaceCard from "./PlaceCard.tsx";
import { ChatError, checkHealth, sendChat } from "./api.ts";
import { toAssistantMessage } from "./format.ts";
import type { ChatMessage } from "./types.ts";

const EXAMPLES = [
  { text: "30개월 아기랑 이번 토요일 오전 10시에 강남역에서 출발해요" },
  { text: "18개월, 내일 오후 1시에 판교역에서 출발해요. 실내 위주로요" },
  { text: "24개월 아기, 모레 아침 9시에 잠실역에서 출발해요. 서울숲 같은 곳" },
];
const WELCOME: ChatMessage = {
  role: "assistant",
  texts: ["안녕하세요! 오늘은 어디로 놀러 가볼까요? 🧺\n아기 월령, 출발지, 날짜와 출발 시각을 알려주시면 아기와 함께 가기 좋은 곳 5곳을 찾아드려요."],
  cards: [],
  choices: [],
};

export default function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([WELCOME]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(false);
  const [online, setOnline] = useState(true);
  const pendingRef = useRef<HTMLDivElement>(null);
  const lastTurnRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const wasPending = useRef(false);

  useEffect(() => {
    checkHealth().then(setOnline);
  }, []);

  // When an answer arrives, put the cursor back in the composer so a follow-up question can
  // be answered right away (also after clicking an example or a choice button).
  // preventScroll: the scroll effect below decides where the page sits.
  useEffect(() => {
    if (wasPending.current && !pending) inputRef.current?.focus({ preventScroll: true });
    wasPending.current = pending;
  }, [pending]);

  // While waiting, keep the "working on it" bubble in sight above the sticky composer;
  // when the answer arrives, scroll to where it starts (not past its cards to the end).
  useEffect(() => {
    if (messages.length === 1 && !pending) return; // welcome screen: stay at the top
    const frame = requestAnimationFrame(() => {
      const behavior: ScrollBehavior = window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "auto"
        : "smooth";
      if (pending) {
        pendingRef.current?.scrollIntoView({ behavior, block: "end" });
      } else {
        lastTurnRef.current?.scrollIntoView({ behavior, block: "start" });
      }
    });
    return () => cancelAnimationFrame(frame);
  }, [messages.length, pending]);

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
          <Message
            key={i}
            message={m}
            onChoose={send}
            disabled={pending}
            turnRef={i === messages.length - 1 ? lastTurnRef : undefined}
          />
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
          <div className="turn assistant" ref={pendingRef}>
            <div className="bubble assistant pending" role="status">
              <span className="dots keep-motion" aria-hidden="true"><i className="keep-motion" /><i className="keep-motion" /><i className="keep-motion" /></span>
              나들이 장소를 찾고 날씨·후기를 살펴보고 있어요. 10~20초쯤 걸려요.
            </div>
          </div>
        )}
      </main>

      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
      >
        {/* not disabled while waiting: a disabled input drops focus; sending is blocked in send() */}
        <input
          ref={inputRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="예: 30개월 아기랑 이번 토요일 오전 10시에 강남역에서 출발해요"
          maxLength={500}
          aria-label="메시지"
          aria-busy={pending}
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
  turnRef?: Ref<HTMLDivElement>;
}

function Hero() {
  return (
    <section className="hero" aria-label="소개">
      <h2>아기와 함께라면 어디든 소풍이에요</h2>
      <p>수유실·유모차 대여·주차부터 날씨와 미세먼지까지 한 번에 확인해 드릴게요.</p>
    </section>
  );
}

function Message({ message, onChoose, disabled, turnRef }: MessageProps) {
  const { role, texts, notice, cards = [], choices = [] } = message;
  const bubbles = texts.map((t, i) => (
    <div key={i} className={`bubble ${role}${i > 0 ? " follow" : ""}`}>
      {t}
    </div>
  ));
  return (
    <div className={`turn ${role}`} ref={turnRef}>
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
