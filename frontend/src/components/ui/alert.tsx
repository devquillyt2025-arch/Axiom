import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { AlertTriangle, CheckCircle2, Info, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";

const alertVariants = cva("flex gap-3 rounded-lg border p-3 text-[13px] leading-5", {
  variants: {
    variant: {
      info: "border-info/30 bg-info/10 text-foreground [&>svg]:text-info",
      warn: "border-warn/40 bg-warn/10 text-foreground [&>svg]:text-warn",
      error: "border-loss/40 bg-loss/10 text-foreground [&>svg]:text-loss",
      success: "border-profit/30 bg-profit/10 text-foreground [&>svg]:text-profit",
    },
  },
  defaultVariants: { variant: "info" },
});

const icons = { info: Info, warn: AlertTriangle, error: XCircle, success: CheckCircle2 } as const;

export interface AlertProps extends Omit<React.HTMLAttributes<HTMLDivElement>, "title">, VariantProps<typeof alertVariants> {
  title?: React.ReactNode;
  action?: React.ReactNode;
}

/** role="alert" for errors/warnings so assistive tech announces them; "status" otherwise. */
export function Alert({ className, variant = "info", title, action, children, ...props }: AlertProps) {
  const Icon = icons[variant ?? "info"];
  return (
    <div
      role={variant === "error" || variant === "warn" ? "alert" : "status"}
      className={cn(alertVariants({ variant }), className)}
      {...props}
    >
      <Icon className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1">
        {title && <p className="font-medium">{title}</p>}
        {children && <div className={cn(title && "mt-0.5 text-muted-foreground")}>{children}</div>}
      </div>
      {action && <div className="shrink-0 self-center">{action}</div>}
    </div>
  );
}
