import { getFilm } from "@/lib/api"
import { Navigation } from "@/components/navigation"
import { FilmForm } from "@/components/film-form"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import Link from "next/link"
import { ArrowLeft } from "lucide-react"

export default async function EditFilmPage({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = await params
  try {
    const data = await getFilm(Number(id))
    if (!data || !(data as any).film) {
      throw new Error("Film not found")
    }
    const { film } = data
    return (
      <div className="min-h-screen bg-background">
        <Navigation />
        <main className="mx-auto max-w-3xl px-4 py-8 sm:px-6 lg:px-8">
          <div className="mb-6">
            <Button variant="outline" size="sm" asChild>
              <Link href={`/films/${id}`}>
                <ArrowLeft className="mr-2 h-4 w-4" />
                Back to Film
              </Link>
            </Button>
          </div>

          <div className="mb-8">
            <h1 className="text-3xl font-bold">Edit Film</h1>
            <p className="mt-1 text-muted-foreground">Update film roll information</p>
          </div>

          <FilmForm film={film} />
        </main>
      </div>
    )
  } catch (e) {
    return (
      <div className="min-h-screen bg-background">
        <Navigation />
        <main className="mx-auto max-w-3xl px-4 py-8 sm:px-6 lg:px-8">
          <div className="mb-6">
            <Button variant="outline" size="sm" asChild>
              <Link href={`/films/${id}`}>
                <ArrowLeft className="mr-2 h-4 w-4" />
                Back to Film
              </Link>
            </Button>
          </div>

          <Card>
            <CardContent>
              <p className="text-sm text-muted-foreground">Failed to load film for editing or it may not exist. Please try again.</p>
            </CardContent>
          </Card>
        </main>
      </div>
    )
  }
}
