import { redirect } from "next/navigation"

/** `/l/12`: what a location's QR code points at (M4). */
export default async function LocationShortPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  redirect(`/locations/${encodeURIComponent(id)}`)
}
