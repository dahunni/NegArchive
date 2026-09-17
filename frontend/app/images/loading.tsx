import { FrameGridSkeleton } from "@/components/skeletons"
import { Skeleton } from "@/components/ui/skeleton"

export default function Loading() {
  return (
    <div className="space-y-6">
      <Skeleton className="h-9 w-40" />
      <Skeleton className="h-11 w-64" />
      <Skeleton className="h-32 w-full rounded-lg" />
      <FrameGridSkeleton />
    </div>
  )
}
