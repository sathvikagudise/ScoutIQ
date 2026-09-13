import type { ReactNode } from "react";
import { cn } from "../../utils/cn";
import "./ui.css";

type Tone =
  | "neutral"
  | "accent"
  | "success"
  | "warning"
  | "danger"
  | "info";

export type { Tone };

interface BadgeProps {
  children: ReactNode;
  tone?: Tone;
  className?: string;
}

export function Badge({ children, tone = "neutral", className }: BadgeProps) {
  return (
    <span className={cn("badge", `badge-${tone}`, className)}>{children}</span>
  );
}