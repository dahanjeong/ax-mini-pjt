// What the place display helpers (../format.ts) hand back.

export type FacilityTone = "yes" | "no" | "fail" | "unknown";

export interface DriveView {
  label: string;
  verified: boolean;
  basis: string; // e.g. "11월 14일 09:00 출발 기준", "" when unknown
}

export interface SourceLink {
  href: string;
  kind: string;
  title: string;
}
