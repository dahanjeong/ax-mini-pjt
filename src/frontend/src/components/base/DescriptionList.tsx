import { Fragment, type ReactNode } from "react";

export interface DescriptionItem {
  term: ReactNode;
  detail: ReactNode;
  key?: string;
}

export interface DescriptionListProps {
  items: DescriptionItem[];
  classNames?: { root?: string; term?: string; detail?: string };
}

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
