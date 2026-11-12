import {
  driveView, dustText, facilityTone, failedText, includesText, settingLabel, sourceLinks, summaryLines, weatherText,
} from "./format.ts";
import type { PlaceCardData } from "./types.ts";

interface Props {
  card: PlaceCardData;
  rank: number;
}

export default function PlaceCard({ card, rank }: Props) {
  const summary = summaryLines(card.review_summary);
  const includes = includesText(card.includes);
  const failed = failedText(card.failed_sources);
  const match = card.preference_match;
  const drive = driveView(card.drive);
  const sources = sourceLinks(card.review_sources);

  return (
    <article className="place-card">
      <header className="place-head">
        <span className="rank num" aria-label={`${rank}위`}>{rank}</span>
        <div className="place-title">
          <h3>{card.name}</h3>
          <p className="meta">
            <span className={`badge suit-${card.age_suitability}`}>월령 {card.age_suitability}</span>
            <span className="badge">{settingLabel(card.indoor_outdoor)}</span>
            <span className="distance">직선거리 <span className="num">{card.distance_km}km</span></span>
            {drive.verified ? (
              <span
                className="drive num"
                title={`${drive.basis || "나들이 날 출발 기준"} 예상 교통 상황으로 계산한 시간이에요.`}
              >
                {drive.label}
                {drive.basis && <span className="drive-basis"> ({drive.basis})</span>}
              </span>
            ) : (
              <span
                className="badge drive-unverified"
                title="직선거리로 추린 후보예요. 출발 전 지도 앱으로 실제 이동시간을 확인해 주세요."
              >
                {drive.label}
              </span>
            )}
          </p>
          {includes && <p className="includes">함께 있는 곳: {includes}</p>}
        </div>
      </header>

      {card.warnings.length > 0 && (
        <p className="warning">{card.warnings.join(", ")} 예보가 있어요. 야외 일정은 주의하세요.</p>
      )}

      <ul className="facilities">
        {Object.entries(card.facilities).map(([key, f]) => (
          <li key={key} className={`facility ${facilityTone(f.status)}`}>
            <span className="facility-label">{f.label}</span>
            <strong>{f.status}</strong>
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

      {sources.length > 0 && (
        <div className="sources">
          <span className="sources-label">후기 출처</span>
          <ul>
            {sources.map((s) => (
              <li key={s.href}>
                <a href={s.href} target="_blank" rel="noopener noreferrer nofollow">
                  <span className="source-kind">{s.kind}</span>
                  <span className="source-title">{s.title}</span>
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}

      {failed && <p className="failed">{failed}</p>}
    </article>
  );
}
