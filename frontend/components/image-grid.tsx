"use client"

import { type Image as ImageType, getImageUrl } from "@/lib/api"
import Image from "next/image"
import Link from "next/link"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"

interface ImageGridProps {
  images: ImageType[]
  filmStartDate?: string | null
  filmEndDate?: string | null
}

function formatDate(dateStr: string | null | undefined): string | null {
  if (!dateStr) return null
  try {
    return new Date(dateStr).toLocaleDateString()
  } catch {
    return dateStr
  }
}

export function ImageGrid({ images, filmStartDate, filmEndDate }: ImageGridProps) {
  if (images.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border py-16 text-center">
        <p className="text-lg font-medium text-muted-foreground">No images yet</p>
        <p className="mt-1 text-sm text-muted-foreground">Upload images to this film roll to see them here.</p>
      </div>
    )
  }

  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-4">
      {images.map((image) => (
        <Link key={image.id} href={`/images/${image.id}`}>
          <Card className="group overflow-hidden transition-shadow hover:shadow-lg">
            <div className="relative aspect-square overflow-hidden bg-muted">
              <Image
                src={getImageUrl(image) || "/placeholder.svg"}
                alt={`Frame ${image.frame_number || "unknown"}`}
                fill
                className="object-cover transition-transform group-hover:scale-105"
                sizes="(max-width: 768px) 50vw, (max-width: 1024px) 33vw, 25vw"
              />
            </div>
            <CardContent className="p-3">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium">{image.type === "scan" ? "Scan" : "Contact Sheet"}</span>
                {image.frame_number && (
                  <Badge variant="secondary" className="text-xs">
                    #{image.frame_number}
                  </Badge>
                )}
              </div>
              {(() => {
                const capture = formatDate(image.capture_date)
                const fallbackRange = filmStartDate && filmEndDate
                  ? `${formatDate(filmStartDate)} – ${formatDate(filmEndDate)}`
                  : null
                const text = capture || fallbackRange
                return text ? (
                  <p className="mt-1 text-xs text-muted-foreground">{text}</p>
                ) : null
              })()}
            </CardContent>
          </Card>
        </Link>
      ))}
    </div>
  )
}
