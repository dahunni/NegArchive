import { notFound } from "next/navigation"

import { ApiError, getCameras, getFilm, getFilms, getFilmstocks, getLenses } from "@/lib/api"
import { RollWorkspace } from "@/components/roll-workspace"

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

  const [rolls, cameras, lenses, filmstocks] = await Promise.all([
    getFilms(),
    getCameras(),
    getLenses(),
    getFilmstocks(),
  ])

  return (
    <RollWorkspace
      film={data.film}
      frames={data.images}
      contactSheets={data.contact_sheets}
      rolls={rolls}
      cameras={cameras}
      lenses={lenses}
      filmstocks={filmstocks}
      editOnOpen={edit === "1"}
    />
  )
}
