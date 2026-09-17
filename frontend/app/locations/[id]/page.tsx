import { notFound } from "next/navigation"

import { ApiError, getLocation, getLocations, getSleeveLayouts } from "@/lib/api"
import { LocationDetail } from "@/components/location-detail"

export default async function LocationPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const locationId = Number(id)
  if (!Number.isFinite(locationId)) notFound()
  let detail
  try {
    detail = await getLocation(locationId)
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound()
    throw error
  }
  const [locations, layouts] = await Promise.all([getLocations(), getSleeveLayouts()])
  return <LocationDetail detail={detail} locations={locations} layouts={layouts} />
}
