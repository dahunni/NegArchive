import { getCameras, getFilmsPage, getFilmstocks, getLenses, getLocations, getWork } from "@/lib/api"
import { type RollSearchParams, queryFromSearchParams } from "@/lib/roll-query"
import { RollBrowser } from "@/components/roll-browser"

/**
 * Rolls are the home page: a roll is the unit of work, so it is what you land on.
 * The gear catalog is fetched here as well, because the filters and both dialogs
 * need it and one server round trip beats three client fetches.
 *
 * M3: the filters live in the query string and are applied by the API, so only
 * the first page of matching rolls crosses the wire — and `/?q=harbour` is a URL
 * you can bookmark.
 */
export default async function RollsHomePage({
  searchParams,
}: {
  searchParams: Promise<RollSearchParams>
}) {
  const params = await searchParams
  const query = queryFromSearchParams(params)

  const [films, cameras, lenses, filmstocks, locations, work] = await Promise.all([
    getFilmsPage(query),
    getCameras(),
    getLenses(),
    getFilmstocks(),
    getLocations().catch(() => []),
    getWork().catch(() => null),
  ])

  return (
    <RollBrowser
      initial={films}
      initialQuery={query}
      openWizard={params.new === "1"}
      focusSearch={params.focus === "search"}
      cameras={cameras}
      lenses={lenses}
      filmstocks={filmstocks}
      locations={locations}
      work={work}
    />
  )
}
