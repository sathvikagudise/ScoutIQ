import type { ReactNode } from "react";
import { cn } from "../../utils/cn";
import "./ui.css";

interface SectionHeaderProps {
  eyebrow?: string;
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
}

export function SectionHeader({
  eyebrow,
  title,
  description,
  action,
  className,
}: SectionHeaderProps) {
  return (
    <header className={cn("section-header", className)}>
      <div className="section-header-copy">
        {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
        <h1 className="section-title">{title}</h1>
        {description ? (
          <p className="section-description">{description}</p>
        ) : null}
      </div>
      {action ? <div className="section-action">{action}</div> : null}
    </header>
  );
}