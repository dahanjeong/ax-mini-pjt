// Shapes of the backend API (src/backend/api/schemas.py, supervisor/cards.py; docs/api-spec.md).

export type FacilityKey = "nursing_room" | "stroller_rental" | "parking";

export interface Facility {
  label: string;
  status: string; // 있음 · 없음 · 정보 없음 · 정보를 불러오지 못함
  source: string | null;
}

export interface Weather {
  forecast_source?: "short_term" | "mid_term";
  precip_prob_max?: number;
  temp_max?: number;
  temp_min?: number;
  status?: string; // set instead of the values when there is no forecast
}

export interface Dust {
  forecast_source?: "daily" | "weekly";
  pm10_grade?: string;
  pm25_grade?: string;
  status?: string;
}

export interface Evidence {
  doc_id: string;
  text: string;
}

export interface PreferenceMatch {
  level: "높음" | "보통" | "낮음";
  evidence: Evidence[];
}

export interface ReviewSource {
  title: string;
  link: string; // http(s) only
  source: "blog" | "cafe" | null;
}

export interface Drive {
  status: string; // 확인됨 · 이동시간 확인 필요
  minutes: number | null; // expected car minutes when 확인됨
  departure_time: string | null; // "YYYY-MM-DDTHH:MM" (KST) the estimate assumes leaving at
}

export interface PlaceCardData {
  name: string;
  distance_km: number;
  indoor_outdoor: "indoor" | "outdoor" | null;
  age_suitability: "적합" | "보통" | "부적합";
  facilities: Record<FacilityKey, Facility>;
  weather: Weather;
  dust: Dust;
  is_bad_day: boolean;
  warnings: string[];
  review_summary: string[];
  review_sources: ReviewSource[];
  failed_sources: string[];
  preference_match: PreferenceMatch | null;
  includes: string[];
  drive: Drive;
}

export interface Candidate {
  name: string;
  address?: string | null;
  lat?: number;
  lng?: number;
}

export interface ChatResponse {
  session_id: string;
  status: "ask" | "ready";
  intent: string;
  reply: string | null;
  messages: string[];
  notice: string | null;
  missing_inputs: string[];
  candidates: Candidate[];
  available_date_range: { start: string; end: string } | null;
  baby_age_months: number | null;
  travels_during_nap: boolean | null;
  departure_location: Candidate | null;
  outing_date: string | null;
  departure_time: string | null; // "HH:MM" (KST)
  exclude_keywords: string[]; // kinds of place ("물놀이") or place names left out, kept until reset
  include_keywords: string[]; // kinds asked to be added to the list ("물놀이도 추천해주세요")
  preference_text: string | null;
  reference_place: string | null;
  reference_candidates: Candidate[];
  // only when this turn ran the recommendation
  result_cards: PlaceCardData[] | null;
  max_drive_hours: number | null;
  radius_km: number | null;
  radius_expanded: boolean | null;
  failed_sources: string[] | null;
  elapsed_s: number | null;
  preference_status: string | null;
}

// one entry of the chat transcript
export interface Choice {
  label: string;
  send: string;
}

export type Role = "user" | "assistant" | "error";

export interface ChatMessage {
  role: Role;
  texts: string[];
  notice?: string | null;
  cards?: PlaceCardData[];
  choices?: Choice[];
}
