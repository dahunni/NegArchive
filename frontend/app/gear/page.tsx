import { getCameras, getFilmstocks, getLenses } from "@/lib/api"
import { GearSection } from "@/components/gear-section"

export default async function GearPage() {
  const [cameras, lenses, filmstocks] = await Promise.all([getCameras(), getLenses(), getFilmstocks()])

  return <GearSection cameras={cameras} lenses={lenses} filmstocks={filmstocks} />
}
