// Pure display helpers (tested with `npm test`).

const FAIL = "정보를 불러오지 못함";
const NO_DUST = "미세먼지 예보 없음";

const SOURCE_LABELS = {
  tourapi: "관광공사 장소", kakao: "카카오 장소", public_data: "공공 편의시설", naver: "후기",
  kma: "날씨", airkorea: "미세먼지", llm: "AI 판정", embedding: "취향 비교", keyword_search: "키워드 검색",
};
const FORECAST_LABELS = { short_term: "단기예보", mid_term: "중기예보", daily: "일별 예보", weekly: "주간 예보" };

export function weatherText(w) {
  if (!w || w.status) return w?.status || FAIL;
  const src = FORECAST_LABELS[w.forecast_source] ? ` (${FORECAST_LABELS[w.forecast_source]})` : "";
  return `강수확률 ${w.precip_prob_max}% · ${w.temp_min}~${w.temp_max}℃${src}`;
}

export function dustText(d) {
  if (!d || d.status) return d?.status || NO_DUST;
  const src = FORECAST_LABELS[d.forecast_source] ? ` (${FORECAST_LABELS[d.forecast_source]})` : "";
  if (d.pm10_grade === "예보 없음") return `초미세먼지 ${d.pm25_grade}${src}`;
  return `미세먼지 ${d.pm10_grade} · 초미세먼지 ${d.pm25_grade}${src}`;
}

export function settingLabel(io) {
  return io === "indoor" ? "실내" : io === "outdoor" ? "야외" : "실내/야외 미상";
}

export function facilityTone(status) {
  if (status === "있음") return "yes";
  if (status === "없음") return "no";
  if (status === FAIL) return "fail";
  return "unknown";
}

export function includesText(names, max = 3) {
  if (!names || names.length === 0) return "";
  const shown = names.slice(0, max).join(", ");
  return names.length > max ? `${shown} 외 ${names.length - max}곳` : shown;
}

export function failedText(sources) {
  if (!sources || sources.length === 0) return "";
  const labels = [...new Set(sources.map((s) => SOURCE_LABELS[s] || s))];
  return `일부 정보를 불러오지 못했어요: ${labels.join(", ")}`;
}

export function summaryLines(lines) {
  return (lines || []).filter((l) => l && l !== FAIL);
}

// One /chat response -> one assistant message for the transcript.
export function toAssistantMessage(view) {
  const texts = view.messages && view.messages.length ? view.messages : view.reply ? [view.reply] : [];
  const choices = (view.reference_candidates && view.reference_candidates.length
    ? view.reference_candidates
    : view.candidates || []
  ).map((c, i) => ({ label: c.address ? `${c.name} (${c.address})` : c.name, send: String(i + 1) }));
  return {
    role: "assistant",
    texts,
    notice: view.notice || null,
    cards: view.result_cards || [],
    choices: view.status === "ask" ? choices : [],
  };
}
