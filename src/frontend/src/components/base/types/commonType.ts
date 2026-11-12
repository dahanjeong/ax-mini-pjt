// Shapes shared by several base components.
import type { HTMLAttributes } from "react";

export type DivProps = HTMLAttributes<HTMLDivElement>;

// className for each named part of a multi-part component: ClassNames<"root" | "input">
export type ClassNames<Part extends string> = Partial<Record<Part, string>>;

// A free-form tone, rendered as data-tone for the styled layer to read.
export interface ToneProps<Tone extends string = string> {
  tone?: Tone;
}

// Element attributes plus a tone: TonedProps<HTMLSpanElement>
export type TonedProps<E extends HTMLElement = HTMLDivElement, Tone extends string = string> =
  HTMLAttributes<E> & ToneProps<Tone>;

// A controlled string that is handed back as a string, not as an event.
export interface ValueProps {
  value: string;
  onValueChange: (value: string) => void;
}
