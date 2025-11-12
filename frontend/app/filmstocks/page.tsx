import { getFilmstocks } from "@/lib/api"
import { Navigation } from "@/components/navigation"
import { FilmstocksList } from "@/components/filmstocks-list"
import { Button } from "@/components/ui/button"
import Link from "next/link"
import { Plus } from "lucide-react"

export default async function FilmstocksPage() {
  const filmstocks = await getFilmstocks()

  return (
    <div className="min-h-screen bg-background">
      <Navigation />
      <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        <div className="mb-8 flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold">Filmstocks</h1>
            <p className="mt-1 text-muted-foreground">Manage your film stock catalog</p>
          </div>
          <Button asChild>
            <Link href="/filmstocks/new">
              <Plus className="mr-2 h-4 w-4" />
              New Filmstock
            </Link>
          </Button>
        </div>
        <FilmstocksList filmstocks={filmstocks} />
      </main>
    </div>
  )
}
