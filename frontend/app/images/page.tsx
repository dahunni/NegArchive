import { getFilms, getImagesPage } from "@/lib/api"
import { FramesBrowser } from "@/components/frames-browser"

/**
 * M3: the first page of frames is server-rendered and every later one is fetched.
 * The roll list is still fetched whole, because it feeds the "Move to roll"
 * picker and a `<select>` of rolls has to hold all of them to be useful.
 */
export default async function FramesPage() {
  const [frames, rolls] = await Promise.all([getImagesPage({ type: "scan" }), getFilms()])
  return <FramesBrowser initial={frames} rolls={rolls} />
}
