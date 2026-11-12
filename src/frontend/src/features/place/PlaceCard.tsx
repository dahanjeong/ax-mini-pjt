import { Badge, Callout, DefinitionList } from "../../components/ui/index.ts";
import { dustText, failedText, includesText, settingLabel, sourceLinks, summaryLines, weatherText } from "./format.ts";
import { DriveInfo } from "./DriveInfo.tsx";
import { FacilityGrid } from "./FacilityGrid.tsx";
import { PreferenceMatch } from "./PreferenceMatch.tsx";
import { ReviewSources } from "./ReviewSources.tsx";
import { SUITABILITY_TONE } from "./tones.ts";
import type { PlaceCardListProps, PlaceCardProps } from "./types/index.ts";
import "../../components/ui/styles/commonStyle.css";
import "./styles/commonStyle.css";
import "./styles/PlaceCard.css";

// One recommended place: rank tile, badges, facilities, weather and air, reviews.
export function PlaceCard({ card, rank }: PlaceCardProps) {
  const summary = summaryLines(card.review_summary);
  const includes = includesText(card.includes);
  const failed = failedText(card.failed_sources);
  const sources = sourceLinks(card.review_sources);

  return (
    <article className="surface-paper place-card">
      <header className="place-head">
        <span className="rank num" aria-label={`${rank}위`}>{rank}</span>
        <div className="place-title">
          <h3>{card.name}</h3>
          <p className="meta">
            <Badge tone={SUITABILITY_TONE[card.age_suitability]}>월령 {card.age_suitability}</Badge>
            <Badge>{settingLabel(card.indoor_outdoor)}</Badge>
            <span className="distance">직선거리 <span className="num">{card.distance_km}km</span></span>
            <DriveInfo drive={card.drive} />
          </p>
          {includes && <p className="muted-note includes">함께 있는 곳: {includes}</p>}
        </div>
      </header>

      {card.warnings.length > 0 && (
        <Callout tone="warning">{card.warnings.join(", ")} 예보가 있어요. 야외 일정은 주의하세요.</Callout>
      )}

      <FacilityGrid facilities={card.facilities} />

      <DefinitionList
        items={[
          { key: "weather", term: "날씨", detail: weatherText(card.weather) },
          { key: "dust", term: "대기", detail: dustText(card.dust) },
        ]}
      />

      {card.preference_match && <PreferenceMatch match={card.preference_match} />}

      {summary.length > 0 && (
        <ul className="summary">
          {summary.map((line, i) => (
            <li key={i}>{line}</li>
          ))}
        </ul>
      )}

      {sources.length > 0 && <ReviewSources sources={sources} />}

      {failed && <p className="muted-note">{failed}</p>}
    </article>
  );
}

// The ranked list of place cards under an answer.
export function PlaceCardList({ cards }: PlaceCardListProps) {
  return (
    <div className="cards">
      {cards.map((card, i) => (
        <PlaceCard key={`${card.name}-${i}`} card={card} rank={i + 1} />
      ))}
    </div>
  );
}
