import { Suspense } from "react"

import { getCameras, getFilmsPage, getFilmstocks, getLenses } from "@/lib/api"
import { type RollSearchParams, queryFromSearchParams } from "@/lib/roll-query"
import { RollBrowser } from "@/components/roll-browser"
import { RollListSkeleton } from "@/components/skeletons"

/**
 * The roll list moved to `/` in M1. `/films` keeps working — old bookmarks, the
 * README and the future QR labels all point here — and renders exactly the same page.
 */
export default async function FilmsPage({
  searchParams,
}: {
  searchParams: Promise<RollSearchParams>
}) {
  const params = await searchParams
  const query = queryFromSearchParams(params)

  const [films, cameras, lenses, filmstocks] = await Promise.all([
    getFilmsPage(query),
    getCameras(),
    getLenses(),
    getFilmstocks(),
  ])

  return (
    <Suspense fallback={<RollListSkeleton />}>
      <RollBrowser
        initial={films}
        initialQuery={query}
        openWizard={params.new === "1"}
        cameras={cameras}
        lenses={lenses}
        filmstocks={filmstocks}
      />
    </Suspense>
  )
}
