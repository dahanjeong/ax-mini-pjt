// Run with `npm test` (node's built-in test runner; node strips the types, no extra tools).
import { test } from "node:test";
import assert from "node:assert/strict";

import { toAssistantMessage } from "./format.ts";
import type { ChatResponse } from "../../api/index.ts";

function response(fields: Partial<ChatResponse>): ChatResponse {
  return {
    session_id: "s", status: "ask", intent: "ask", reply: null, messages: [], notice: null, missing_inputs: [],
    candidates: [], available_date_range: null, baby_age_months: null, travels_during_nap: null,
    departure_location: null, outing_date: null, departure_time: null, exclude_keywords: [], include_keywords: [], preference_text: null, reference_place: null,
    reference_candidates: [], result_cards: null, max_drive_hours: null, radius_km: null, radius_expanded: null,
    failed_sources: null, elapsed_s: null, preference_status: null, ...fields,
  };
}

test("assistant message from a /chat response", () => {
  const ask = toAssistantMessage(response({
    status: "ask", reply: "어디에서 출발하시나요?", messages: ["어디에서 출발하시나요?"],
    candidates: [{ name: "서울시청", address: "서울 중구" }, { name: "수원시청", address: "경기 수원시" }],
  }));
  assert.deepEqual(ask.texts, ["어디에서 출발하시나요?"]);
  assert.deepEqual(ask.choices, [
    { label: "서울시청 (서울 중구)", send: "1" }, { label: "수원시청 (경기 수원시)", send: "2" }]);
  assert.deepEqual(ask.cards, []);

  const ready = toAssistantMessage(response({
    status: "ready", messages: ["입력이 모두 확인됐어요.", "주변 장소를 찾고 있어요..."],
    result_cards: [], notice: "조건에 맞는 장소가 3곳뿐이에요.",
    reference_candidates: [{ name: "서울숲" }],
  }));
  assert.equal(ready.notice, "조건에 맞는 장소가 3곳뿐이에요.");
  assert.deepEqual(ready.choices, []);               // choices only while asking

  const reset = toAssistantMessage(response({
    status: "ask", notice: "처음부터 다시 할게요.",
    messages: ["처음부터 다시 할게요. 아기는 몇 개월인가요? (0~72개월)"],
  }));
  assert.equal(reset.notice, null);                  // already in the reply: not shown twice
});
