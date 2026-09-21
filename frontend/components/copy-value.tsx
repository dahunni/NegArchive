"use client"

import { useEffect, useRef, useState } from "react"
import { Check, Copy } from "lucide-react"

import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"

/**
 * A value with a copy button: a path, an address or a command that has to be
 * pasted into another application, so the steps are useless if it is retyped.
 *
 * `path` truncates a long value on one line; `command` keeps it whole and lets it
 * scroll, because a command with the middle missing cannot be read back.
 */
export function CopyValue({
  value,
  label,
  variant = "path",
  className,
}: {
  value: string
  /** What is being copied, for the button's accessible name. Defaults to the value. */
  label?: string
  variant?: "path" | "command"
  className?: string
}) {
  const [copied, setCopied] = useState(false)
  const timer = useRef<number | null>(null)

  // The tick goes back to a clipboard after 1.5 s — unless the row is gone by then.
  useEffect(
    () => () => {
      if (timer.current !== null) window.clearTimeout(timer.current)
    },
    [],
  )

  return (
    <div className={cn("flex min-w-0 gap-2", variant === "path" ? "mt-1 items-center" : "items-stretch", className)}>
      <code
        className={cn(
          "min-w-0 flex-1 bg-muted px-2 py-1.5 type-numeric",
          variant === "path"
            ? "truncate rounded text-sm"
            : "overflow-x-auto rounded-md border border-border bg-muted/50 whitespace-pre text-xs",
        )}
        title={value}
      >
        {value}
      </code>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="min-h-9 shrink-0"
        aria-label={`Copy ${label ?? value}`}
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(value)
            setCopied(true)
            if (timer.current !== null) window.clearTimeout(timer.current)
            timer.current = window.setTimeout(() => setCopied(false), 1500)
          } catch {
            // A browser that refuses the clipboard is not an error worth a toast:
            // the text is right there to select.
          }
        }}
      >
        {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
      </Button>
    </div>
  )
}
