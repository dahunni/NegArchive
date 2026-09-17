import { Suspense } from "react"

import { getCameras, getFilms, getFilmstocks, getLenses } from "@/lib/api"
import { RollBrowser } from "@/components/roll-browser"
import { RollListSkeleton } from "@/components/skeletons"

/**
 * Rolls are the home page: a roll is the unit of work, so it is what you land on.
 * The gear catalog is fetched here as well, because the filters and both dialogs
 * need it and one server round trip beats three client fetches.
 */
export default async function RollsHomePage() {
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
