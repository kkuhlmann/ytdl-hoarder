import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const badgeVariants = cva(
  "inline-flex items-center rounded-md border px-2.5 py-0.5 text-xs font-semibold font-mono transition-colors focus:outline-hidden focus:ring-2 focus:ring-ring focus:ring-offset-2",
  {
    variants: {
      variant: {
        default:
          "border-transparent bg-primary/20 text-primary shadow-sm",
        secondary:
          "border-transparent bg-secondary text-secondary-foreground",
        destructive:
          "border-transparent bg-status-error/20 text-status-error shadow-sm",
        outline: "text-foreground border-border",
        // Status variants for task states
        success:
          "border-status-success/30 bg-status-success/10 text-status-success",
        error:
          "border-status-error/30 bg-status-error/10 text-status-error",
        warning:
          "border-status-warning/30 bg-status-warning/10 text-status-warning",
        info:
          "border-status-info/30 bg-status-info/10 text-status-info",
        queued:
          "border-status-queued/30 bg-status-queued/10 text-status-queued",
        // Matrix style
        matrix:
          "border-matrix/30 bg-matrix/10 text-matrix",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <div className={cn(badgeVariants({ variant }), className)} {...props} />
  )
}

export { Badge, badgeVariants }
