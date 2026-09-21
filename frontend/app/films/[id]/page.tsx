import { notFound } from "next/navigation"

import {
  ApiError,
  getCameras,
  getFilm,
  getFilmsPage,
  getFilmstocks,
  getLenses,
  getLocations,
  getRollMoves,
} from "@/lib/api"
import { RollWorkspace } from "@/components/roll-workspace"

/**
 * How many rolls the workspace's "move these frames to…" picker offers. It is a
 * picker, not a list, so it takes one page instead of the whole archive (M3, R#20).
 */
const ROLL_PICKER_LIMIT = 200

export default async function RollPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>
  searchParams: Promise<{ edit?: string }>
}) {
  const { id } = await params
  const { edit } = await searchParams
  const rollId = Number(id)
  if (!Number.isFinite(rollId)) notFound()

  let data
  try {
    data = await getFilm(rollId)
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound()
    throw error
  }

  const [rollPage, cameras, lenses, filmstocks, locations, moves] = await Promise.all([
    getFilmsPage({ limit: ROLL_PICKER_LIMIT }),
    getCameras(),
    getLenses(),
    getFilmstocks(),
    getLocations().catch(() => []),
    getRollMoves(rollId).catch(() => []),
  ])

  return (
    <RollWorkspace
      film={data.film}
      frames={data.images}
      contactSheets={data.contact_sheets}
      rolls={rollPage.items}
      cameras={cameras}
      lenses={lenses}
      filmstocks={filmstocks}
      locations={locations}
      moves={moves}
      editOnOpen={edit === "1"}
    />
  )
}
