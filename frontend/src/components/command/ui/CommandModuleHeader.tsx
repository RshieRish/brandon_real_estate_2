import Link from 'next/link';
import type { ReactNode } from 'react';

export type CommandBreadcrumb = Readonly<{
  label: string;
  href?: string;
}>;

export type CommandModuleHeaderProps = Readonly<{
  breadcrumbs?: readonly CommandBreadcrumb[];
  title: string;
  description?: string;
  actions?: ReactNode;
  tabs?: ReactNode;
  toolbar?: ReactNode;
}>;

export function CommandModuleHeader({
  breadcrumbs = [],
  title,
  description,
  actions,
  tabs,
  toolbar,
}: CommandModuleHeaderProps) {
  return (
    <header className="command-module-header command-content-gutters">
      <div className="command-module-title-row">
        <div>
          {breadcrumbs.length > 0 ? (
            <nav aria-label="Breadcrumb">
              <ol className="command-breadcrumbs">
                {breadcrumbs.map((breadcrumb, index) => (
                  <li key={`${breadcrumb.label}-${index}`}>
                    {breadcrumb.href ? <Link href={breadcrumb.href}>{breadcrumb.label}</Link> : <span aria-current="page">{breadcrumb.label}</span>}
                  </li>
                ))}
              </ol>
            </nav>
          ) : null}
          <h1>{title}</h1>
          {description ? <p>{description}</p> : null}
        </div>
        {actions ? (
          <div role="group" aria-label={`${title} actions`} className="command-module-actions">
            {actions}
          </div>
        ) : null}
      </div>
      {tabs ? <div className="command-module-tabs">{tabs}</div> : null}
      {toolbar ? (
        <div role="region" aria-label={`${title} tools`} className="command-module-toolbar">
          {toolbar}
        </div>
      ) : null}
    </header>
  );
}
