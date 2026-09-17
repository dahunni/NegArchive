import { Suspense } from "react"

import { getCameras, getFilmstocks, getLenses } from "@/lib/api"
import { GearSection } from "@/components/gear-section"
import { GearSkeleton } from "@/components/skeletons"

export default async function GearPage() {
  const [cameras, lenses, filmstocks] = await Promise.all([getCameras(), getLenses(), getFilmstocks()])

  return (
    <Suspense fallback={<GearSkeleton />}>
      <GearSection cameras={cameras} lenses={lenses} filmstocks={filmstocks} />
    </Suspense>
  )
}
