// Run with `npm test` (node's built-in test runner; node strips the types, no extra tools).
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  dustText, facilityTone, failedText, includesText, settingLabel, summaryLines, weatherText,
} from "./format.ts";

test("weather and dust texts", () => {
  assert.equal(
    weatherText({ forecast_source: "short_term", precip_prob_max: 60, temp_max: 14, temp_min: 11 }),
    "강수확률 60% · 11~14℃ (단기예보)",
  );
  assert.equal(weatherText({ status: "정보를 불러오지 못함" }), "정보를 불러오지 못함");
  assert.equal(weatherText(null), "정보를 불러오지 못함");
  assert.equal(dustText({ pm10_grade: "보통", pm25_grade: "나쁨", forecast_source: "daily" }),
    "미세먼지 보통 · 초미세먼지 나쁨 (일별 예보)");
  assert.equal(dustText({ pm10_grade: "예보 없음", pm25_grade: "낮음", forecast_source: "weekly" }),
    "초미세먼지 낮음 (주간 예보)");
  assert.equal(dustText({ status: "미세먼지 예보 없음" }), "미세먼지 예보 없음");
});

test("labels and tones", () => {
  assert.equal(settingLabel("indoor"), "실내");
  assert.equal(settingLabel("outdoor"), "야외");
  assert.equal(facilityTone("있음"), "yes");
  assert.equal(facilityTone("없음"), "no");
  assert.equal(facilityTone("정보 없음"), "unknown");
  assert.equal(facilityTone("정보를 불러오지 못함"), "fail");
});

test("includes, failed sources, summary", () => {
  assert.equal(includesText([]), "");
  assert.equal(includesText(["a", "b"]), "a, b");
  assert.equal(includesText(["a", "b", "c", "d", "e"]), "a, b, c 외 2곳");
  assert.equal(failedText(["kma", "airkorea", "kma"]), "일부 정보를 불러오지 못했어요: 날씨, 미세먼지");
  assert.equal(failedText([]), "");
  assert.deepEqual(summaryLines(["좋아요", "정보를 불러오지 못함"]), ["좋아요"]);
});

test("drive time and review source links", async () => {
  const { driveView, sourceLinks } = await import("./format.ts");
  const at = "2026-11-14T09:00";
  assert.deepEqual(driveView({ status: "확인됨", minutes: 18.4, departure_time: at }),
    { label: "차로 약 18분", verified: true, basis: "11월 14일 09:00 출발 기준" });
  assert.equal(driveView({ status: "확인됨", minutes: 95, departure_time: at }).label, "차로 약 1시간 35분");
  assert.equal(driveView({ status: "확인됨", minutes: 60, departure_time: null }).label, "차로 약 1시간");
  assert.equal(driveView({ status: "확인됨", minutes: 60, departure_time: null }).basis, "");
  assert.deepEqual(driveView({ status: "이동시간 확인 필요", minutes: null, departure_time: at }),
    { label: "이동시간 확인 필요", verified: false, basis: "11월 14일 09:00 출발 기준" });
  assert.deepEqual(driveView(undefined), { label: "이동시간 확인 필요", verified: false, basis: "" });
  assert.deepEqual(
    sourceLinks([
      { title: "서울숲 아기랑", link: "http://localhost/blog/1", source: "blog" },
      { title: "x", link: "javascript:alert(1)", source: "cafe" },
      { title: "", link: "http://localhost/cafe/2", source: null },
    ]),
    [
      { href: "http://localhost/blog/1", kind: "블로그", title: "서울숲 아기랑" },
      { href: "http://localhost/cafe/2", kind: "후기", title: "http://localhost/cafe/2" },
    ],
  );
});
