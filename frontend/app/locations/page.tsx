import { getLocations, getSettings, getSleeveLayouts, getSystemInfo } from "@/lib/api"
import { LocationTree } from "@/components/location-tree"

export const metadata = { title: "Locations — NegArchive" }

/** The storage tree (M4). Fetched whole: even a large archive has a few hundred nodes. */
export default async function LocationsPage() {
  const [locations, layouts, settings, info] = await Promise.all([
    getLocations(),
    getSleeveLayouts(),
    getSettings().catch(() => null),
    getSystemInfo().catch(() => null),
  ])
  const publicBase = (settings?.settings.public_base_url || info?.ui_url || "").replace(/\/$/, "")
  return <LocationTree locations={locations} layouts={layouts} publicBase={publicBase} />
}
