import * as React from "react";
import { cn } from "@/lib/utils";

// text-base on mobile (16px) stops iOS Safari zooming the page when an input is focused
const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, type, ...props }, ref) => (
    <input
      type={type}
      ref={ref}
      className={cn(
        "flex h-11 w-full rounded-md border border-input bg-muted/40 px-3 py-1 text-base transition-colors duration-150 placeholder:text-muted-foreground/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 md:h-9 md:text-sm",
        type === "number" && "num",
        className,
      )}
      {...props}
    />
  ),
);
Input.displayName = "Input";

export { Input };
