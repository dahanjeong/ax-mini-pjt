import React, { useEffect, useState } from "react";
import PlaceCard from "./PlaceCard.jsx";

const API = "http://localhost:8000";

export default function App() {
  const [status, setStatus] = useState("확인 중...");

  useEffect(() => {
    fetch(`${API}/health`)
      .then((r) => r.json())
      .then((d) => setStatus(d.status))
      .catch(() => setStatus("서버에 연결할 수 없음"));
  }, []);

  return (
    <main>
      <h1>아기와 나들이</h1>
      <p>백엔드 상태: {status}</p>
      <ChatMessages messages={[]} />
    </main>
  );
}

// Chat transcript: text bubbles plus place cards for any message carrying result_cards.
export function ChatMessages({ messages }) {
  return (
    <section className="chat">
      {messages.map((m, i) => (
        <div key={i} className={`bubble ${m.role}`}>
          {m.text && <p>{m.text}</p>}
          {(m.result_cards || []).map((c, j) => (
            <PlaceCard key={j} card={c} />
          ))}
        </div>
      ))}
    </section>
  );
}
