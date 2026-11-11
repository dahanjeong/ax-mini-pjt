import React from "react";
import {
  dustText, facilityTone, failedText, includesText, settingLabel, summaryLines, weatherText,
} from "./format.js";

export default function PlaceCard({ card, rank }) {
  const summary = summaryLines(card.review_summary);
  const includes = includesText(card.includes);
  const failed = failedText(card.failed_sources);
  const match = card.preference_match;

  return (
    <article className="place-card">
      <header className="place-head">
        <span className="rank">{rank}</span>
        <div className="place-title">
          <h3>{card.name}</h3>
          <p className="meta">
            <span className={`badge suit-${card.age_suitability}`}>월령 {card.age_suitability}</span>
            <span className="badge">{settingLabel(card.indoor_outdoor)}</span>
            <span>직선거리 {card.distance_km}km</span>
          </p>
          {includes && <p className="includes">함께 있는 곳: {includes}</p>}
        </div>
      </header>

      {card.warnings.length > 0 && (
        <p className="warning">⚠ {card.warnings.join(" · ")} 예보가 있어요. 야외 일정은 주의하세요.</p>
      )}

      <ul className="facilities">
        {Object.entries(card.facilities).map(([key, f]) => (
          <li key={key} className={`facility ${facilityTone(f.status)}`}>
            {f.label} <strong>{f.status}</strong>
          </li>
        ))}
      </ul>

      <dl className="conditions">
        <dt>날씨</dt>
        <dd>{weatherText(card.weather)}</dd>
        <dt>대기</dt>
        <dd>{dustText(card.dust)}</dd>
      </dl>

      {match && (
        <div className="match">
          <p>
            취향 일치 <span className={`badge level-${match.level}`}>{match.level}</span>
          </p>
          {match.evidence.map((e) => (
            <blockquote key={e.doc_id}>{e.text}</blockquote>
          ))}
        </div>
      )}

      {summary.length > 0 && (
        <ul className="summary">
          {summary.map((line, i) => (
            <li key={i}>{line}</li>
          ))}
        </ul>
      )}

      {failed && <p className="failed">{failed}</p>}
    </article>
  );
}
