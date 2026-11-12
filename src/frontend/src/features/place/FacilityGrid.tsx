import { facilityTone } from "./format.ts";
import type { FacilityGridProps } from "./types/index.ts";
import "../../components/ui/styles/commonStyle.css";
import "./styles/commonStyle.css";
import "./styles/FacilityGrid.css";

// Nursing room, stroller rental and parking as three cells tinted by status.
export function FacilityGrid({ facilities }: FacilityGridProps) {
  return (
    <ul className="facilities">
      {Object.entries(facilities).map(([key, f]) => (
        <li key={key} className="soft-cell facility" data-tone={facilityTone(f.status)}>
          <span className="facility-label">{f.label}</span>
          <strong>{f.status}</strong>
        </li>
      ))}
    </ul>
  );
}
