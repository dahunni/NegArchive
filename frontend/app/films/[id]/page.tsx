import { getFilm } from "@/lib/api"
import { Navigation } from "@/components/navigation"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import Link from "next/link"
import { ArrowLeft, Pencil } from "lucide-react"
import { ImageGrid } from "@/components/image-grid"
import { FilmDumpActions } from "@/components/film-dump-actions"

export default async function FilmDetailPage({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = await params
  let film: Awaited<ReturnType<typeof getFilm>>["film"]
  let images: Awaited<ReturnType<typeof getFilm>>["images"]
  try {
    const data = await getFilm(Number(id))
    // Handle backend not_found shape gracefully
    if (!data || !(data as any).film) {
      throw new Error("Film not found")
    }
    film = data.film
    images = data.images
  } catch (e) {
    return (
      <div className="min-h-screen bg-background">
        <Navigation />
        <main className="mx-auto max-w-3xl px-4 py-8 sm:px-6 lg:px-8">
          <div className="mb-6 flex items-center gap-4">
            <Button variant="outline" size="sm" asChild>
              <Link href="/films">
                <ArrowLeft className="mr-2 h-4 w-4" />
                Back to Films
              </Link>
            </Button>
          </div>
          <Card>
            <CardHeader>
              <CardTitle>Failed to load film</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">There was an error fetching this film or it may not exist. Please try again.</p>
            </CardContent>
          </Card>
        </main>
      </div>
    )
  }

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return null
    return new Date(dateStr).toLocaleDateString()
  }

  // Date rendering is handled in the client ImageGrid using film's date range

  return (
    <div className="min-h-screen bg-background">
      <Navigation />
      <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        <div className="mb-6 flex items-center gap-4">
          <Button variant="outline" size="sm" asChild>
            <Link href="/films">
              <ArrowLeft className="mr-2 h-4 w-4" />
              Back to Films
            </Link>
          </Button>
        </div>

        <div className="mb-8 flex items-start justify-between">
          <div>
            <h1 className="text-3xl font-bold">{film.title}</h1>
            <p className="mt-1 text-muted-foreground">Film #{film.archive_serial || film.id}</p>
          </div>
          <Button asChild>
            <Link href={`/films/${film.id}/edit`}>
              <Pencil className="mr-2 h-4 w-4" />
              Edit Film
            </Link>
          </Button>
        </div>

        <div className="mb-8 grid gap-6 md:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>Equipment</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              <div>
                <span className="text-sm font-medium">Camera:</span>{" "}
                <span className="text-sm text-muted-foreground">{film.camera || "Not specified"}</span>
              </div>
              <div>
                <span className="text-sm font-medium">Lens:</span>{" "}
                <span className="text-sm text-muted-foreground">{film.lens || "Not specified"}</span>
              </div>
              <div>
                <span className="text-sm font-medium">Film Type:</span>{" "}
                <span className="text-sm text-muted-foreground">{film.film_type || "Not specified"}</span>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Details</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              <div>
                <span className="text-sm font-medium">Date Range:</span>{" "}
                <span className="text-sm text-muted-foreground">
                  {film.start_date && film.end_date
                    ? `${formatDate(film.start_date)} – ${formatDate(film.end_date)}`
                    : film.start_date
                      ? formatDate(film.start_date)
                      : "Not specified"}
                </span>
              </div>
              <div>
                <span className="text-sm font-medium">Building:</span>{" "}
                <span className="text-sm text-muted-foreground">{film.building || "Not specified"}</span>
              </div>
              <div>
                <span className="text-sm font-medium">Folder:</span>{" "}
                <span className="text-sm text-muted-foreground">{film.folder || "Not specified"}</span>
              </div>
            </CardContent>
          </Card>
        </div>

        {film.notes && (
          <Card className="mb-8">
            <CardHeader>
              <CardTitle>Notes</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">{film.notes}</p>
            </CardContent>
          </Card>
        )}

        <div className="mb-8">
          <h2 className="mb-4 text-2xl font-semibold">Actions</h2>
          <FilmDumpActions filmId={film.id} />
        </div>

        <div>
          <h2 className="mb-4 text-2xl font-semibold">Images ({images.length})</h2>
          <ImageGrid images={images} filmStartDate={film.start_date} filmEndDate={film.end_date} />
        </div>
      </main>
    </div>
  )
}
