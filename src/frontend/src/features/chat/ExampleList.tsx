import { useId } from "react";
import { Tile, TileGroup } from "../../components/ui/index.ts";
import "./chat.css";

interface Props {
  examples: string[];
  onPick: (text: string) => void;
}

// Example questions to send with one tap on the welcome screen.
export function ExampleList({ examples, onPick }: Props) {
  const labelId = useId();
  return (
    <>
      <h2 className="examples-label" id={labelId}>이렇게 물어보세요</h2>
      <TileGroup aria-labelledby={labelId}>
        {examples.map((text) => (
          <Tile key={text} variant="example" onClick={() => onPick(text)}>
            {text}
          </Tile>
        ))}
      </TileGroup>
    </>
  );
}
