"use client"

import { ErrorState } from "@/components/error-state"

export default function Error({ error, reset }: { error: Error; reset: () => void }) {
  return <ErrorState title="Could not open this frame" error={error} reset={reset} />
}
