import { Suspense } from "react"

import { getCameras, getFilms, getFilmstocks, getLenses } from "@/lib/api"
import { RollBrowser } from "@/components/roll-browser"
import { RollListSkeleton } from "@/components/skeletons"

/**
 * The roll list moved to `/` in M1. `/films` keeps working — old bookmarks, the
 * README and the future QR labels all point here — and renders exactly the same page.
 */
export default async function FilmsPage() {
  const [films, cameras, lenses, filmstocks] = await Promise.all([
    getFilms(),
    getCameras(),
    getLenses(),
    getFilmstocks(),
  ])

  return (
    <Suspense fallback={<RollListSkeleton />}>
      <RollBrowser films={films} cameras={cameras} lenses={lenses} filmstocks={filmstocks} />
    </Suspense>
  )
}
