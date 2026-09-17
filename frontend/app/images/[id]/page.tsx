import { notFound } from "next/navigation"

import { ApiError, getFilm, getFilms, getImage, getImages } from "@/lib/api"
import { FrameViewerRoute } from "@/components/frame-viewer-route"

/**
 * `/images/{id}` opens the viewer. The neighbouring frames come from the same roll
 * (or from the loose frames), so previous/next works when you arrive by URL.
 */
export default async function FramePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const frameId = Number(id)
  if (!Number.isFinite(frameId)) notFound()

  let frame
  try {
    frame = await getImage(frameId)
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound()
    throw error
  }

  const rolls = await getFilms()
  let siblings = [frame]
  if (frame.film_roll_id) {
    const roll = await getFilm(frame.film_roll_id)
    const pool = frame.type === "contact_sheet" ? roll.contact_sheets : roll.images
    if (pool.some((item) => item.id === frame.id)) siblings = pool
  } else {
    const loose = (await getImages()).filter((item) => item.film_roll_id === null)
    if (loose.some((item) => item.id === frame.id)) siblings = loose
  }

  const startIndex = Math.max(
    0,
    siblings.findIndex((item) => item.id === frame.id),
  )
  const backTo = frame.film_roll_id ? `/films/${frame.film_roll_id}` : "/images"

  return <FrameViewerRoute frames={siblings} startIndex={startIndex} rolls={rolls} backTo={backTo} />
}
