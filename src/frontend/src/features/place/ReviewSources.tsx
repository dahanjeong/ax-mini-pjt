import { ExternalLink } from "../../components/base/index.ts";
import type { SourceLink } from "../../format.ts";

// Links to the blog / cafe reviews the summary was written from.
export function ReviewSources({ sources }: { sources: SourceLink[] }) {
  return (
    <div className="sources">
      <span className="sources-label">후기 출처</span>
      <ul>
        {sources.map((s) => (
          <li key={s.href}>
            <ExternalLink href={s.href}>
              <span className="source-kind">{s.kind}</span>
              <span className="source-title">{s.title}</span>
            </ExternalLink>
          </li>
        ))}
      </ul>
    </div>
  );
}
