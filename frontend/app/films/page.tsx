import { getFilms } from "@/lib/api"
import { FilmsList } from "@/components/films-list"
import { Navigation } from "@/components/navigation"
import { Button } from "@/components/ui/button"
import Link from "next/link"
import { Plus } from "lucide-react"

export default async function FilmsPage() {
  const films = await getFilms()

  return (
    <div className="min-h-screen bg-background">
      <Navigation />
      <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        <div className="mb-8 flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold">Films</h1>
            <p className="mt-1 text-muted-foreground">Manage your film rolls and photography archive</p>
          </div>
          <Button asChild>
            <Link href="/films/new">
              <Plus className="mr-2 h-4 w-4" />
              New Film
            </Link>
          </Button>
        </div>
        <FilmsList films={films} />
      </main>
    </div>
  )
}
