import { useRef, useState } from "react";
import { Composer } from "./components/ui/index.ts";
import { ExampleList, Hero, Message, PendingTurn, TopBar, useChat } from "./features/chat/index.ts";
import { useChatScroll } from "./hooks/useChatScroll.ts";
import { useFocusWhenSettled } from "./hooks/useFocusWhenSettled.ts";
import type { ChatMessage } from "./features/chat/index.ts";

const EXAMPLES = [
  "30개월 아기랑 이번 토요일 오전 10시에 강남역에서 출발해요",
  "18개월, 내일 오후 1시에 판교역에서 출발해요. 실내 위주로요",
  "24개월 아기, 모레 아침 9시에 잠실역에서 출발해요. 서울숲 같은 곳",
];
const WELCOME: ChatMessage = {
  role: "assistant",
  texts: ["안녕하세요! 오늘은 어디로 놀러 가볼까요? 🧺\n아기 월령, 출발지, 날짜와 출발 시각을 알려주시면 아기와 함께 가기 좋은 곳 5곳을 찾아드려요."],
  cards: [],
  choices: [],
};

export default function App() {
  const { messages, pending, online, canRestart, send, restart } = useChat(WELCOME);
  const [input, setInput] = useState("");
  const pendingRef = useRef<HTMLDivElement>(null);
  const lastTurnRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // back into the composer once an answer arrives (also after clicking an example or a choice)
  useFocusWhenSettled(pending, inputRef);
  useChatScroll({ count: messages.length, pending, pendingRef, lastTurnRef });

  function submit(text: string) {
    if (!text.trim() || pending) return;
    setInput("");
    send(text);
  }

  const showExamples = messages.length === 1 && !pending;

  return (
    <div className="app">
      <TopBar online={online} canRestart={canRestart} onRestart={restart} />

      <main className="chat" aria-live="polite">
        {showExamples && <Hero />}
        {messages.map((m, i) => (
          <Message
            key={i}
            message={m}
            onChoose={submit}
            disabled={pending}
            turnRef={i === messages.length - 1 ? lastTurnRef : undefined}
          />
        ))}
        {showExamples && <ExampleList examples={EXAMPLES} onPick={submit} />}
        {pending && <PendingTurn ref={pendingRef} />}
      </main>

      <Composer
        value={input}
        onValueChange={setInput}
        onSend={submit}
        busy={pending}
        inputRef={inputRef}
        inputLabel="메시지"
        placeholder="예: 30개월 아기랑 이번 토요일 오전 10시에 강남역에서 출발해요"
        maxLength={500}
        submitLabel="보내기"
      />
    </div>
  );
}
