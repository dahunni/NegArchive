import { Skeleton } from "@/components/ui/skeleton"

/** Loading states mirror the layout they replace, so nothing jumps when data lands. */

export function RollListSkeleton() {
  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-2">
          <Skeleton className="h-8 w-32" />
          <Skeleton className="h-4 w-48" />
        </div>
        <Skeleton className="h-11 w-32" />
      </div>
      <Skeleton className="h-28 w-full rounded-lg" />
      <div className="space-y-3">
        {Array.from({ length: 4 }).map((_, index) => (
          <div key={index} className="flex gap-4 rounded-lg border border-border p-4">
            <Skeleton className="h-20 w-44 shrink-0 rounded-md" />
            <div className="flex-1 space-y-2">
              <Skeleton className="h-5 w-56" />
              <Skeleton className="h-4 w-full max-w-lg" />
              <Skeleton className="h-4 w-40" />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export function FrameGridSkeleton({ count = 10 }: { count?: number }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
      {Array.from({ length: count }).map((_, index) => (
        <div key={index} className="space-y-2 rounded-lg border border-border p-2">
          <Skeleton className="aspect-[3/2] w-full rounded-md" />
          <Skeleton className="h-4 w-20" />
          <Skeleton className="h-4 w-full" />
        </div>
      ))}
    </div>
  )
}

export function RollWorkspaceSkeleton() {
  return (
    <div className="space-y-6">
      <Skeleton className="h-9 w-28" />
      <div className="space-y-2">
        <Skeleton className="h-9 w-72" />
        <Skeleton className="h-4 w-56" />
        <Skeleton className="h-4 w-80" />
      </div>
      <Skeleton className="h-52 w-full rounded-lg" />
      <Skeleton className="h-32 w-full rounded-lg" />
      <FrameGridSkeleton />
    </div>
  )
}

export function GearSkeleton() {
  return (
    <div className="space-y-6">
      <Skeleton className="h-9 w-24" />
      <Skeleton className="h-10 w-80" />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {Array.from({ length: 6 }).map((_, index) => (
          <div key={index} className="space-y-3 rounded-lg border border-border p-3">
            <Skeleton className="aspect-[3/2] w-full rounded-md" />
            <Skeleton className="h-5 w-32" />
            <Skeleton className="h-9 w-full" />
          </div>
        ))}
      </div>
    </div>
  )
}
