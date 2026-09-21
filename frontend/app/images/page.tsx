import { getFilmsPage, getImagesPage } from "@/lib/api"
import { FramesBrowser } from "@/components/frames-browser"

/**
 * M3: the first page of frames is server-rendered and every later one is fetched.
 * The roll list feeds the "Move to roll" picker; one page at the backend's
 * maximum is as many as a `<select>` can usefully hold anyway.
 */
export default async function FramesPage() {
  const [frames, rolls] = await Promise.all([getImagesPage({ type: "scan" }), getFilmsPage({ limit: 500 })])
  return <FramesBrowser initial={frames} rolls={rolls.items} />
}
