import { getImages, getFilms } from "@/lib/api"
import { Navigation } from "@/components/navigation"
import { ImagesList } from "@/components/images-list"
import { Button } from "@/components/ui/button"
import Link from "next/link"
import { Upload } from "lucide-react"

export default async function ImagesPage({
  searchParams,
}: {
  searchParams: Promise<{ film_id?: string }>
}) {
  const { film_id } = await searchParams
  const images = await getImages(film_id ? Number(film_id) : undefined)
  const films = await getFilms()

  return (
    <div className="min-h-screen bg-background">
      <Navigation />
      <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        <div className="mb-8 flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold">Images</h1>
            <p className="mt-1 text-muted-foreground">Browse and manage your scanned images</p>
          </div>
          <Button asChild>
            <Link href="/images/upload">
              <Upload className="mr-2 h-4 w-4" />
              Upload Image
            </Link>
          </Button>
        </div>
        <ImagesList images={images} films={films} selectedFilmId={film_id} />
      </main>
    </div>
  )
}
