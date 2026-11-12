// Pure display helpers (tested with `npm test`).
import type { ChatMessage, ChatResponse, Choice, Drive, Dust, ReviewSource, Weather } from "./types.ts";

const FAIL = "정보를 불러오지 못함";
const NO_DUST = "미세먼지 예보 없음";

const SOURCE_LABELS: Record<string, string> = {
  tourapi: "관광공사 장소", kakao: "카카오 장소", public_data: "공공 편의시설", naver: "후기",
  kma: "날씨", airkorea: "미세먼지", llm: "AI 판정", embedding: "취향 비교", keyword_search: "키워드 검색",
  kakao_navi: "이동시간",
};
const DRIVE_CONFIRMED = "확인됨";
const DRIVE_UNVERIFIED = "이동시간 확인 필요";
const REVIEW_KIND_LABELS: Record<string, string> = { blog: "블로그", cafe: "카페" };
const FORECAST_LABELS: Record<string, string> = {
  short_term: "단기예보", mid_term: "중기예보", daily: "일별 예보", weekly: "주간 예보",
};

function sourceSuffix(source: string | undefined): string {
  const label = source ? FORECAST_LABELS[source] : undefined;
  return label ? ` (${label})` : "";
}

export function weatherText(w: Weather | null | undefined): string {
  if (!w || w.status) return w?.status || FAIL;
  return `강수확률 ${w.precip_prob_max}% · ${w.temp_min}~${w.temp_max}℃${sourceSuffix(w.forecast_source)}`;
}

export function dustText(d: Dust | null | undefined): string {
  if (!d || d.status) return d?.status || NO_DUST;
  const src = sourceSuffix(d.forecast_source);
  if (d.pm10_grade === "예보 없음") return `초미세먼지 ${d.pm25_grade}${src}`;
  return `미세먼지 ${d.pm10_grade} · 초미세먼지 ${d.pm25_grade}${src}`;
}

export function settingLabel(io: string | null | undefined): string {
  return io === "indoor" ? "실내" : io === "outdoor" ? "야외" : "실내/야외 미상";
}

export type FacilityTone = "yes" | "no" | "fail" | "unknown";

export function facilityTone(status: string): FacilityTone {
  if (status === "있음") return "yes";
  if (status === "없음") return "no";
  if (status === FAIL) return "fail";
  return "unknown";
}

export function includesText(names: string[] | null | undefined, max = 3): string {
  if (!names || names.length === 0) return "";
  const shown = names.slice(0, max).join(", ");
  return names.length > max ? `${shown} 외 ${names.length - max}곳` : shown;
}

export function failedText(sources: string[] | null | undefined): string {
  if (!sources || sources.length === 0) return "";
  const labels = [...new Set(sources.map((s) => SOURCE_LABELS[s] || s))];
  return `일부 정보를 불러오지 못했어요: ${labels.join(", ")}`;
}

export interface DriveView {
  label: string;
  verified: boolean;
  basis: string; // e.g. "11월 14일 09:00 출발 기준", "" when unknown
}

// "2026-11-14T09:00" -> "11월 14일 09:00 출발 기준"
function departureBasis(when: string | null | undefined): string {
  const m = /^\d{4}-(\d{2})-(\d{2})T(\d{2}:\d{2})$/.exec(when || "");
  return m ? `${Number(m[1])}월 ${Number(m[2])}일 ${m[3]} 출발 기준` : "";
}

// Expected car time (future traffic at the outing's departure time) when the backend
// checked it, else the "needs checking" label.
export function driveView(d: Drive | null | undefined): DriveView {
  const basis = departureBasis(d?.departure_time);
  if (d && d.status === DRIVE_CONFIRMED && typeof d.minutes === "number") {
    const m = Math.round(d.minutes);
    const text = m >= 60 ? `${Math.floor(m / 60)}시간${m % 60 ? ` ${m % 60}분` : ""}` : `${m}분`;
    return { label: `차로 약 ${text}`, verified: true, basis };
  }
  return { label: DRIVE_UNVERIFIED, verified: false, basis };
}

export interface SourceLink {
  href: string;
  kind: string;
  title: string;
}

// Review links to show under the summary; anything but http(s) is dropped.
export function sourceLinks(sources: ReviewSource[] | null | undefined): SourceLink[] {
  return (sources || [])
    .filter((s) => s && typeof s.link === "string" && /^https?:\/\//.test(s.link))
    .map((s) => ({ href: s.link, kind: (s.source && REVIEW_KIND_LABELS[s.source]) || "후기", title: s.title || s.link }));
}

export function summaryLines(lines: string[] | null | undefined): string[] {
  return (lines || []).filter((l) => l && l !== FAIL);
}

// One /chat response -> one assistant message for the transcript.
export function toAssistantMessage(view: ChatResponse): ChatMessage {
  const texts = view.messages && view.messages.length ? view.messages : view.reply ? [view.reply] : [];
  const pool = view.reference_candidates && view.reference_candidates.length
    ? view.reference_candidates
    : view.candidates || [];
  const choices: Choice[] = pool.map((c, i) => ({
    label: c.address ? `${c.name} (${c.address})` : c.name,
    send: String(i + 1),
  }));
  // the backend often repeats the notice at the start of the reply: show it only once
  const notice = view.notice && !texts.some((t) => t.includes(view.notice as string)) ? view.notice : null;
  return {
    role: "assistant",
    texts,
    notice,
    cards: view.result_cards || [],
    choices: view.status === "ask" ? choices : [],
  };
}
