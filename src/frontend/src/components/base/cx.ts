// Joins class names, skipping falsy parts: cx("a", cond && "b", undefined) -> "a b".
export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}
