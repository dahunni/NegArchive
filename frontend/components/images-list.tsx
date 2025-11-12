"use client"

import { type Image as ImageType, type Film, getImageUrl } from "@/lib/api"
import { useState } from "react"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Label } from "@/components/ui/label"
import Image from "next/image"
import Link from "next/link"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { useRouter } from "next/navigation"

interface ImagesListProps {
  images: ImageType[]
  films: Film[]
  selectedFilmId?: string
}

export function ImagesList({ images, films, selectedFilmId }: ImagesListProps) {
  const router = useRouter()
  const [filmFilter, setFilmFilter] = useState(selectedFilmId || "all")

  const handleFilterChange = (value: string) => {
    setFilmFilter(value)
    if (value === "all") {
      router.push("/images")
    } else {
      router.push(`/images?film_id=${value}`)
    }
  }

  if (images.length === 0) {
    return (
      <div>
        <div className="mb-6 max-w-xs">
          <Label htmlFor="film-filter">Filter by Film</Label>
          <Select value={filmFilter} onValueChange={handleFilterChange}>
            <SelectTrigger id="film-filter">
              <SelectValue placeholder="All films" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All films</SelectItem>
              {films.map((film) => (
                <SelectItem key={film.id} value={film.id.toString()}>
                  {film.title}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border py-16 text-center">
          <p className="text-lg font-medium text-muted-foreground">No images found</p>
          <p className="mt-1 text-sm text-muted-foreground">
            {filmFilter !== "all"
              ? "This film has no images yet. Try uploading some!"
              : "Upload your first image to get started."}
          </p>
        </div>
      </div>
    )
  }

  return (
    <div>
      <div className="mb-6 max-w-xs">
        <Label htmlFor="film-filter">Filter by Film</Label>
        <Select value={filmFilter} onValueChange={handleFilterChange}>
          <SelectTrigger id="film-filter">
            <SelectValue placeholder="All films" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All films ({images.length})</SelectItem>
            {films.map((film) => (
              <SelectItem key={film.id} value={film.id.toString()}>
                {film.title}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
        {images.map((image) => {
          const film = films.find((f) => f.id === image.film_roll_id)
          return (
            <Link key={image.id} href={`/images/${image.id}`}>
              <Card className="group overflow-hidden transition-shadow hover:shadow-lg">
                <div className="relative aspect-square overflow-hidden bg-muted">
                  <Image
                    src={getImageUrl(image) || "/placeholder.svg"}
                    alt={`Frame ${image.frame_number || "unknown"}`}
                    fill
                    className="object-cover transition-transform group-hover:scale-105"
                    sizes="(max-width: 768px) 50vw, (max-width: 1024px) 33vw, (max-width: 1280px) 25vw, 20vw"
                  />
                </div>
                <CardContent className="p-3">
                  <div className="flex items-center justify-between">
                    <span className="truncate text-xs font-medium">{image.type === "scan" ? "Scan" : "Contact"}</span>
                    {image.frame_number && (
                      <Badge variant="secondary" className="text-xs">
                        #{image.frame_number}
                      </Badge>
                    )}
                  </div>
                  {film && <p className="mt-1 truncate text-xs text-muted-foreground">{film.title}</p>}
                  {image.capture_date && (
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      {new Date(image.capture_date).toLocaleDateString()}
                    </p>
                  )}
                </CardContent>
              </Card>
            </Link>
          )
        })}
      </div>
    </div>
  )
}
