// Shapes shared by several styled components.

export type Size = "md" | "sm";

// good: mint · caution: sand · bad: coral
export type StatusTone = "good" | "caution" | "bad";

// Replace a base component's free-form tone with a fixed set: WithTone<BaseBadgeProps, BadgeTone>
export type WithTone<P, Tone extends string> = Omit<P, "tone"> & { tone?: Tone };

// A styled wrapper names its parts' classes itself; callers can only add a class to the root.
export type StyledSlots<P> = Omit<P, "classNames"> & { className?: string };
