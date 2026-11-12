// Shapes shared by the place feature.
import type { PlaceCardData } from "../../../api/index.ts";

// A section that renders some fields of a card as they come: CardFieldProps<"drive"> = { drive: Drive }
export type CardFieldProps<K extends keyof PlaceCardData> = Pick<PlaceCardData, K>;

// A card field the section only renders when it is set.
export type PresentField<K extends keyof PlaceCardData> = NonNullable<PlaceCardData[K]>;
