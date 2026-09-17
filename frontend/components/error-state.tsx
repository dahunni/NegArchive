"use client"

import Link from "next/link"
import { AlertTriangle } from "lucide-react"

import { Button } from "@/components/ui/button"

/**
 * The one error screen. Every `error.tsx` renders it, so a backend that is down looks
 * the same everywhere and always offers a retry.
 */
export function ErrorState({
  title = "Something went wrong",
  error,
  reset,
}: {
  title?: string
  error?: Error
  reset?: () => void
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-destructive/40 px-6 py-16 text-center">
      <AlertTriangle className="mb-3 h-8 w-8 text-destructive" />
      <p className="type-section">{title}</p>
      <p className="mt-1 max-w-md type-body text-muted-foreground">
        {error?.message || "The archive could not be reached. Is the backend running?"}
      </p>
      <div className="mt-5 flex gap-2">
        {reset ? <Button onClick={reset}>Try again</Button> : null}
        <Button variant="outline" asChild>
          <Link href="/">Back to rolls</Link>
        </Button>
      </div>
    </div>
  )
}
