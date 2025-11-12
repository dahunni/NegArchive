import { getFilms, getImages, getFilmstocks } from "@/lib/api"
import { Navigation } from "@/components/navigation"
import { SearchInterface } from "@/components/search-interface"

export default async function SearchPage() {
  const [films, images, filmstocks] = await Promise.all([getFilms(), getImages(), getFilmstocks()])

  return (
    <div className="min-h-screen bg-background">
      <Navigation />
      <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        <div className="mb-8">
          <h1 className="text-3xl font-bold">Search</h1>
          <p className="mt-1 text-muted-foreground">Search across films, images, and your entire archive</p>
        </div>
        <SearchInterface films={films} images={images} filmstocks={filmstocks} />
      </main>
    </div>
  )
}
