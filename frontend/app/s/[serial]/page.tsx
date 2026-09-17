import Link from "next/link"
import { redirect } from "next/navigation"

import { getRollBySerial } from "@/lib/api"
import { EmptyState } from "@/components/empty-state"
import { Button } from "@/components/ui/button"
import { ScanLine } from "lucide-react"

/**
 * `/s/NEG-2024-0011`: what every printed QR code points at (M4). A real
 * server-side redirect, so a phone camera lands on the roll straight away.
 */
export default async function SerialPage({ params }: { params: Promise<{ serial: string }> }) {
  const { serial } = await params
  const roll = await getRollBySerial(decodeURIComponent(serial))
  if (roll) redirect(`/films/${roll.id}`)
  return (
    <EmptyState
      icon={ScanLine}
      title={`No roll carries the serial ${decodeURIComponent(serial).toUpperCase()}`}
      description="The label may belong to an older archive, or the roll was deleted. Search for it by title, or scan another code."
      action={
        <Button asChild>
          <Link href={`/?q=${encodeURIComponent(decodeURIComponent(serial))}`}>Search the archive</Link>
        </Button>
      }
    />
  )
}
