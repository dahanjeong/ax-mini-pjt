import type { Ref } from "react";
import { Bubble, Callout, Tile, TileGroup } from "../../components/ui/index.ts";
import { PlaceCardList } from "../place/index.ts";
import type { ChatMessage } from "../../types.ts";
import "./chat.css";

interface Props {
  message: ChatMessage;
  onChoose: (text: string) => void;
  disabled: boolean;
  turnRef?: Ref<HTMLDivElement>;
}

// One turn of the transcript: bubbles, a notice, numbered choices and place cards.
export function Message({ message, onChoose, disabled, turnRef }: Props) {
  const { role, texts, notice, cards = [], choices = [] } = message;
  return (
    <div className={`turn ${role}`} ref={turnRef}>
      {texts.map((t, i) => (
        <Bubble key={i} from={role} follow={i > 0}>
          {t}
        </Bubble>
      ))}
      {notice && <Callout tone="notice">{notice}</Callout>}
      {choices.length > 0 && (
        <TileGroup aria-label="선택지">
          {choices.map((c) => (
            <Tile key={c.send} variant="choice" leading={c.send} disabled={disabled} onClick={() => onChoose(c.send)}>
              {c.label}
            </Tile>
          ))}
        </TileGroup>
      )}
      {cards.length > 0 && <PlaceCardList cards={cards} />}
    </div>
  );
}
