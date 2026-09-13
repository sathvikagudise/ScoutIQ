import type { ReactNode } from "react";
import { cn } from "../../utils/cn";
import "./ui.css";

interface MetricProps {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  className?: string;
}

export function Metric({ label, value, hint, className }: MetricProps) {
  return (
    <div className={cn("metric", className)}>
      <p className="metric-label">{label}</p>
      <p className="metric-value">{value}</p>
      {hint ? <p className="metric-hint">{hint}</p> : null}
    </div>
  );
}