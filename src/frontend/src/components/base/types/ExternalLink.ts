import type { AnchorHTMLAttributes } from "react";

// target and rel are fixed by the component; href is required
export type ExternalLinkProps = Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "target" | "rel" | "href"> & {
  href: string;
};
