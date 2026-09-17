import type React from "react"

import { cn } from "@/lib/utils"

/**
 * The one empty state in the app. Every list uses it, so "nothing here yet" always
 * looks the same and always offers the next action.
 */
export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
}: {
  icon?: React.ComponentType<{ className?: string }>
  title: string
  description?: string
  action?: React.ReactNode
  className?: string
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center rounded-lg border border-dashed border-border px-6 py-12 text-center sm:py-16",
        className,
      )}
    >
      {Icon ? <Icon className="mb-3 h-8 w-8 text-muted-foreground" /> : null}
      <p className="type-section">{title}</p>
      {description ? <p className="mt-1 max-w-md type-body text-muted-foreground">{description}</p> : null}
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  )
}
