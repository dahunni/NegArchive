import { getFilms, getImages } from "@/lib/api"
import { FramesBrowser } from "@/components/frames-browser"

export default async function FramesPage() {
  const [frames, rolls] = await Promise.all([getImages(), getFilms()])
  return <FramesBrowser frames={frames} rolls={rolls} />
}
