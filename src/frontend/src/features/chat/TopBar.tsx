import { Button, StatusPill } from "../../components/ui/index.ts";
import type { TopBarProps } from "./types/index.ts";
import "../../components/ui/styles/commonStyle.css";
import "./styles/TopBar.css";

export function TopBar({ online, canRestart, onRestart }: TopBarProps) {
  return (
    <header className="sticky-bar topbar">
      <div className="brand">
        <h1>아기랑 나들이</h1>
        <p>우리 가족 주말 나들이, 같이 찾아봐요</p>
      </div>
      <div className="topbar-right">
        {!online && <StatusPill>서버 연결 안 됨</StatusPill>}
        <Button size="sm" onClick={onRestart} disabled={!canRestart}>
          ↺ 처음부터
        </Button>
      </div>
    </header>
  );
}
