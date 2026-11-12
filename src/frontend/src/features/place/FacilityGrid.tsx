import { facilityTone } from "../../format.ts";
import type { Facility } from "../../types.ts";

// Nursing room, stroller rental and parking as three cells tinted by status.
export function FacilityGrid({ facilities }: { facilities: Record<string, Facility> }) {
  return (
    <ul className="facilities">
      {Object.entries(facilities).map(([key, f]) => (
        <li key={key} className="facility" data-tone={facilityTone(f.status)}>
          <span className="facility-label">{f.label}</span>
          <strong>{f.status}</strong>
        </li>
      ))}
    </ul>
  );
}
