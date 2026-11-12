import type { ExternalLinkProps } from "./types/index.ts";

export function isSafeHref(href: string | null | undefined): href is string {
  return typeof href === "string" && /^https?:\/\//.test(href);
}

// Unstyled link that opens in a new tab without giving the other page access to ours.
// Anything but http(s) is rendered as plain text, never as a link.
export function ExternalLink({ href, children, ...rest }: ExternalLinkProps) {
  if (!isSafeHref(href)) return <span className={rest.className}>{children}</span>;
  return (
    <a href={href} target="_blank" rel="noopener noreferrer nofollow" {...rest}>
      {children}
    </a>
  );
}
