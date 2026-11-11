import React from "react";

function weatherText(w) {
  if (!w || w.status) return w?.status || "정보를 불러오지 못함";
  return `강수확률 ${w.precip_prob_max}% · 최고 ${w.temp_max}℃ / 최저 ${w.temp_min}℃`;
}

function dustText(d) {
  if (!d || d.status) return d?.status || "미세먼지 예보 없음";
  return `PM10 ${d.pm10_grade} · PM2.5 ${d.pm25_grade}`;
}

export default function PlaceCard({ card }) {
  return (
    <article className="place-card">
      <h3>{card.name}</h3>
      <p className="distance">직선거리 {card.distance_km}km · {card.indoor_outdoor === "indoor" ? "실내" : "실외"}</p>
      <ul className="facilities">
        {Object.entries(card.facilities).map(([k, f]) => (
          <li key={k}>{f.label}: {f.status}</li>
        ))}
      </ul>
      <p className="weather">날씨: {weatherText(card.weather)}</p>
      <p className="dust">미세먼지: {dustText(card.dust)}</p>
      {card.warnings.length > 0 && (
        <p className="warning">⚠ {card.warnings.join(" · ")} 주의</p>
      )}
      <ol className="summary">
        {card.review_summary.map((line, i) => (
          <li key={i}>{line}</li>
        ))}
      </ol>
    </article>
  );
}
