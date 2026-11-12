import { forwardRef } from "react";
import { TypingIndicator } from "../../components/ui/index.ts";
import "./chat.css";

// The assistant's "working on it" turn while an answer is on its way.
export const PendingTurn = forwardRef<HTMLDivElement>(function PendingTurn(_props, ref) {
  return (
    <div className="turn assistant" ref={ref}>
      <TypingIndicator>나들이 장소를 찾고 날씨·후기를 살펴보고 있어요. 10~20초쯤 걸려요.</TypingIndicator>
    </div>
  );
});
