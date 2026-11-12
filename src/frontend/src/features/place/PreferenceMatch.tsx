import { Badge } from "../../components/ui/index.ts";
import type { PreferenceMatch as Match } from "../../types.ts";
import { MATCH_TONE } from "./tones.ts";

// How close the place is to the place the user said they liked, with quoted evidence.
export function PreferenceMatch({ match }: { match: Match }) {
  return (
    <div className="match">
      <p>
        취향 일치 <Badge tone={MATCH_TONE[match.level]}>{match.level}</Badge>
      </p>
      {match.evidence.map((e) => (
        <blockquote key={e.doc_id}>{e.text}</blockquote>
      ))}
    </div>
  );
}
