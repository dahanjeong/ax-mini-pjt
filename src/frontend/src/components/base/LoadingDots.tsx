export interface LoadingDotsProps {
  count?: number;
  className?: string;
  dotClassName?: string;
}

// Unstyled "working on it" dots; decorative, so hidden from screen readers.
export function LoadingDots({ count = 3, className, dotClassName }: LoadingDotsProps) {
  return (
    <span className={className} aria-hidden="true">
      {Array.from({ length: count }, (_, i) => (
        <i key={i} className={dotClassName} />
      ))}
    </span>
  );
}
