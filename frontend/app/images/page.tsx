import { getFilmsPage, getImagesPage } from "@/lib/api"
import { FramesBrowser } from "@/components/frames-browser"

/**
 * M3: the first page of frames is server-rendered and every later one is fetched.
 * The roll list feeds the "Move to roll" picker; one page at the backend's
 * maximum is as many as a `<select>` can usefully hold anyway.
 *
 * M7: `?q=` is honoured, so "see all frames matching …" in the search palette
 * is a link, and a filtered frames page can be bookmarked like the roll list.
 */
export default async function FramesPage({ searchParams }: { searchParams: Promise<{ q?: string }> }) {
  const params = await searchParams
  const q = (params.q || "").trim() || undefined
  const [frames, rolls] = await Promise.all([getImagesPage({ type: "scan", q }), getFilmsPage({ limit: 500 })])
  return <FramesBrowser initial={frames} initialQuery={q ?? ""} rolls={rolls.items} />
}
