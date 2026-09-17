import Link from "next/link"

import { Button } from "@/components/ui/button"
import { EmptyState } from "@/components/empty-state"

export default function NotFound() {
  return (
    <EmptyState
      title="No such frame"
      description="This frame is not in the archive. It may have been deleted."
      action={
        <Button asChild>
          <Link href="/images">Back to frames</Link>
        </Button>
      }
    />
  )
}
