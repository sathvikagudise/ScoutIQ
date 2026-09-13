import type { ReactNode } from "react";
import { cn } from "../../utils/cn";
import "./ui.css";

interface ButtonProps {
  children: ReactNode;
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md";
  disabled?: boolean;
  onClick?: () => void;
  className?: string;
}

export function Button({
  children,
  variant = "primary",
  size = "md",
  disabled,
  onClick,
  className,
}: ButtonProps) {
  return (
    <button
      type="button"
      className={cn("btn", `btn-${variant}`, `btn-${size}`, className)}
      disabled={disabled}
      onClick={onClick}
    >
      {children}
    </button>
  );
}