import { getImage, getImageUrl, getFilm, getImageDownloadUrl } from "@/lib/api"
import { Navigation } from "@/components/navigation"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import Link from "next/link"
import { ArrowLeft, Pencil, Download } from "lucide-react"
import Image from "next/image"

export default async function ImageDetailPage({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = await params
  let image: Awaited<ReturnType<typeof getImage>>
  try {
    image = await getImage(Number(id))
  } catch (e) {
    image = { id: -1, film_roll_id: null, type: "scan", path: "", url: "", frame_number: null, notes: null, capture_date: null, created_at: new Date().toISOString() }
  }

  const isError = (image as any)?.error

  let film = null
  if (!isError && image.film_roll_id) {
    try {
      const filmData = await getFilm(image.film_roll_id)
      film = filmData.film
    } catch (error) {
      // Film might not exist
    }
  }

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return null
    return new Date(dateStr).toLocaleDateString()
  }

  return (
    <div className="min-h-screen bg-background">
      <Navigation />
      <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        <div className="mb-6 flex items-center gap-4">
          <Button variant="outline" size="sm" asChild>
            <Link href="/images">
              <ArrowLeft className="mr-2 h-4 w-4" />
              Back to Images
            </Link>
          </Button>
        </div>

        {isError && (
          <Card>
            <CardHeader>
              <CardTitle>Image not found</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">We couldn’t load this image. It may have been deleted or the ID is invalid.</p>
              <div className="mt-4">
                <Button asChild>
                  <Link href="/images">Back to Images</Link>
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {!isError && (
          <>
            <div className="mb-8 flex items-start justify-between">
              <div>
                <div className="flex items-center gap-3">
                  <h1 className="text-3xl font-bold">{image.type === "scan" ? "Scan" : "Contact Sheet"}</h1>
                  {image.frame_number && (
                    <Badge variant="secondary" className="text-base">
                      Frame #{image.frame_number}
                    </Badge>
                  )}
                </div>
                {film && (
                  <p className="mt-1 text-muted-foreground">
                    From film:{" "}
                    <Link href={`/films/${film.id}`} className="underline">
                      {film.title}
                    </Link>
                  </p>
                )}
              </div>
              <div className="flex items-center gap-2">
                <Button asChild>
                  <Link href={`/images/${image.id}/edit`}>
                    <Pencil className="mr-2 h-4 w-4" />
                    Edit Image
                  </Link>
                </Button>
                <Button variant="secondary" asChild>
                  <a href={getImageDownloadUrl(image)} target="_blank" rel="noopener noreferrer">
                    <Download className="mr-2 h-4 w-4" />
                    Download
                  </a>
                </Button>
              </div>
            </div>

            <div className="grid gap-8 lg:grid-cols-3">
              <div className="lg:col-span-2">
                <Card className="overflow-hidden">
                  <div className="relative aspect-[4/3] overflow-hidden bg-muted">
                    <Image
                      src={getImageUrl(image) || "/placeholder.svg"}
                      alt={`Frame ${image.frame_number || "unknown"}`}
                      fill
                      className="object-contain"
                      sizes="(max-width: 1024px) 100vw, 66vw"
                      priority
                    />
                  </div>
                </Card>
              </div>

              <div className="space-y-6">
                <Card>
                  <CardHeader>
                    <CardTitle>Details</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <div>
                      <span className="text-sm font-medium">Type:</span>{" "}
                      <span className="text-sm text-muted-foreground">
                        {image.type === "scan" ? "Scan" : "Contact Sheet"}
                      </span>
                    </div>
                    {image.frame_number && (
                      <div>
                        <span className="text-sm font-medium">Frame:</span>{" "}
                        <span className="text-sm text-muted-foreground">#{image.frame_number}</span>
                      </div>
                    )}
                    {image.capture_date && (
                      <div>
                        <span className="text-sm font-medium">Capture Date:</span>{" "}
                        <span className="text-sm text-muted-foreground">{formatDate(image.capture_date)}</span>
                      </div>
                    )}
                    <div>
                      <span className="text-sm font-medium">Created:</span>{" "}
                      <span className="text-sm text-muted-foreground">{formatDate(image.created_at)}</span>
                    </div>
                    {image.path && (
                      <div>
                        <span className="text-sm font-medium">Path:</span>{" "}
                        <span className="text-sm text-muted-foreground break-all">{image.path}</span>
                      </div>
                    )}
                  </CardContent>
                </Card>

                {image.notes && (
                  <Card>
                    <CardHeader>
                      <CardTitle>Notes</CardTitle>
                    </CardHeader>
                    <CardContent>
                      <p className="text-sm text-muted-foreground">{image.notes}</p>
                    </CardContent>
                  </Card>
                )}
              </div>
            </div>
          </>
        )}
      </main>
    </div>
  )
}
