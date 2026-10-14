import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-medium leading-5 whitespace-nowrap",
  {
    variants: {
      variant: {
        default: "border-transparent bg-primary/15 text-info",
        muted: "border-transparent bg-muted text-muted-foreground",
        outline: "border-border text-foreground",
        profit: "border-profit/30 bg-profit/10 text-profit",
        loss: "border-loss/30 bg-loss/10 text-loss",
        warn: "border-warn/40 bg-warn/10 text-warn",
        live: "border-loss/50 bg-loss/15 text-loss",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}
