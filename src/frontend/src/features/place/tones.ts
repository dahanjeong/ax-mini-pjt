// Backend values -> badge tones.
import type { BadgeTone } from "../../components/ui/index.ts";
import type { PlaceCardData, PreferenceMatch } from "../../api/index.ts";

export const SUITABILITY_TONE: Record<PlaceCardData["age_suitability"], BadgeTone> = {
  적합: "good",
  보통: "caution",
  부적합: "bad",
};

export const MATCH_TONE: Record<PreferenceMatch["level"], BadgeTone> = {
  높음: "accent",
  보통: "neutral",
  낮음: "muted",
};
