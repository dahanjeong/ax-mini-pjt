import { Badge } from "../../components/ui/index.ts";
import { driveView } from "../../format.ts";
import type { Drive } from "../../types.ts";

// Expected car time when the backend checked it, else a "check it yourself" badge.
export function DriveInfo({ drive }: { drive: Drive }) {
  const view = driveView(drive);
  if (!view.verified) {
    return (
      <Badge
        tone="caution"
        className="drive-unverified"
        title="직선거리로 추린 후보예요. 출발 전 지도 앱으로 실제 이동시간을 확인해 주세요."
      >
        {view.label}
      </Badge>
    );
  }
  return (
    <span className="drive num" title={`${view.basis || "나들이 날 출발 기준"} 예상 교통 상황으로 계산한 시간이에요.`}>
      {view.label}
      {view.basis && <span className="drive-basis"> ({view.basis})</span>}
    </span>
  );
}
