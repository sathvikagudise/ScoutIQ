import type { ReactNode } from "react";
import { cn } from "../../utils/cn";
import "./ui.css";

interface CardProps {
  children: ReactNode;
  raised?: boolean;
  className?: string;
  tabIndex?: number;
  ariaLabel?: string;
}

export function Card({ children, raised, className, tabIndex, ariaLabel }: CardProps) {
  return (
    <div
      className={cn("card", raised && "card-raised", className)}
      tabIndex={tabIndex}
      aria-label={ariaLabel}
    >
      {children}
    </div>
  );
}