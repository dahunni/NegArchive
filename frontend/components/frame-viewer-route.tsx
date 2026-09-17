"use client"

import { useRouter } from "next/navigation"
import { useState } from "react"

import type { Film, Image as Frame } from "@/lib/api"
import { FrameViewer } from "@/components/frame-viewer"

/**
 * `/images/{id}` is a real route (bookmarks and QR codes point at it), but it renders
 * the viewer, not a separate detail page. Neighbouring frames of the same roll are
 * passed in so previous/next works straight from the URL.
 */
export function FrameViewerRoute({
  frames,
  startIndex,
  rolls,
  backTo,
}: {
  frames: Frame[]
  startIndex: number
  rolls: Film[]
  backTo: string
}) {
  const router = useRouter()
  const [index, setIndex] = useState(startIndex)

  return (
    <FrameViewer
      frames={frames}
      index={index}
      onIndexChange={(next) => {
        setIndex(next)
        // Keep the URL on the frame that is on screen, without a new history entry.
        window.history.replaceState(null, "", `/images/${frames[next].id}`)
      }}
      onClose={() => router.push(backTo)}
      rolls={rolls}
      onChanged={() => router.refresh()}
    />
  )
}
