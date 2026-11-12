import { Badge } from "../../components/ui/index.ts";
import { MATCH_TONE } from "./tones.ts";
import type { PreferenceMatchProps } from "./types/index.ts";
import "./styles/commonStyle.css";
import "./styles/PreferenceMatch.css";

// How close the place is to the place the user said they liked, with quoted evidence.
export function PreferenceMatch({ match }: PreferenceMatchProps) {
  return (
    <div className="match">
      <p>
        취향 일치 <Badge tone={MATCH_TONE[match.level]}>{match.level}</Badge>
      </p>
      {match.evidence.map((e) => (
        <blockquote key={e.doc_id} className="soft-cell">
          {e.text}
        </blockquote>
      ))}
    </div>
  );
}
