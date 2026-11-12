import { Fragment } from "react";
import type { DescriptionListProps } from "./types/index.ts";

// Unstyled term/detail pairs (<dl>).
export function DescriptionList({ items, classNames = {} }: DescriptionListProps) {
  return (
    <dl className={classNames.root}>
      {items.map((item, i) => (
        <Fragment key={item.key ?? i}>
          <dt className={classNames.term}>{item.term}</dt>
          <dd className={classNames.detail}>{item.detail}</dd>
        </Fragment>
      ))}
    </dl>
  );
}
