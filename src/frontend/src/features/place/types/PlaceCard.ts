import type { PlaceCardData } from "../../../api/index.ts";

export interface PlaceCardProps {
  card: PlaceCardData;
  rank: number; // 1-based
}

export interface PlaceCardListProps {
  cards: PlaceCardProps["card"][];
}
