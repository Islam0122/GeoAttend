import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";
import { cn } from "@/lib/utils";

export const badgeVariants = cva("inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold whitespace-nowrap [&_svg]:size-3", {
  variants: {
    tone: {
      success: "bg-primary/12 text-accent-foreground dark:text-primary",
      warning: "bg-warning/15 text-amber-700 dark:text-warning",
      danger: "bg-destructive/12 text-destructive",
      info: "bg-sky-500/12 text-sky-700 dark:text-sky-300",
      neutral: "bg-muted text-muted-foreground",
      outline: "border text-foreground",
    },
  },
  defaultVariants: { tone: "neutral" },
});

export function Badge({ className, tone, ...props }: React.HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}
