import Link from "next/link"

import { Button } from "@/components/ui/button"
import { EmptyState } from "@/components/empty-state"

export default function NotFound() {
  return (
    <EmptyState
      title="No such roll"
      description="This roll is not in the archive. It may have been deleted."
      action={
        <Button asChild>
          <Link href="/">Back to rolls</Link>
        </Button>
      }
    />
  )
}
