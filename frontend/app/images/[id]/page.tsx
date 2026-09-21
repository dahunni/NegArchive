import { notFound } from "next/navigation"

import { ApiError, getFilm, getFilmsPage, getImage, getImagesPage } from "@/lib/api"
import { FrameViewerRoute } from "@/components/frame-viewer-route"

/**
 * How many rolls the "move to roll" picker offers, and how many loose frames the
 * viewer will page through. Both are one page of the API rather than the whole
 * archive (M3, R#20): sending every roll and every frame to open one frame is
 * what the paginated endpoints exist to avoid.
 */
const NEIGHBOURS = 200

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

  const rolls = (await getFilmsPage({ limit: NEIGHBOURS })).items
  let siblings = [frame]
  if (frame.film_roll_id) {
    const roll = await getFilm(frame.film_roll_id)
    const pool = frame.type === "contact_sheet" ? roll.contact_sheets : roll.images
    if (pool.some((item) => item.id === frame.id)) siblings = pool
  } else {
    const loose = (await getImagesPage({ type: "scan", unassigned: true, limit: NEIGHBOURS })).items
    if (loose.some((item) => item.id === frame.id)) siblings = loose
  }

  const startIndex = Math.max(
    0,
    siblings.findIndex((item) => item.id === frame.id),
  )
  const backTo = frame.film_roll_id ? `/films/${frame.film_roll_id}` : "/images"

  return <FrameViewerRoute frames={siblings} startIndex={startIndex} rolls={rolls} backTo={backTo} />
}
