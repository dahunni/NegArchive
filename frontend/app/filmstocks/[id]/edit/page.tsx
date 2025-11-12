import { getFilmstock } from "@/lib/api"
import { Navigation } from "@/components/navigation"
import { FilmstockForm } from "@/components/filmstock-form"
import { Button } from "@/components/ui/button"
import Link from "next/link"
import { ArrowLeft } from "lucide-react"

export default async function EditFilmstockPage({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = await params
  const filmstock = await getFilmstock(Number(id))

  return (
    <div className="min-h-screen bg-background">
      <Navigation />
      <main className="mx-auto max-w-3xl px-4 py-8 sm:px-6 lg:px-8">
        <div className="mb-6">
          <Button variant="outline" size="sm" asChild>
            <Link href="/filmstocks">
              <ArrowLeft className="mr-2 h-4 w-4" />
              Back to Filmstocks
            </Link>
          </Button>
        </div>

        <div className="mb-8">
          <h1 className="text-3xl font-bold">Edit Filmstock</h1>
          <p className="mt-1 text-muted-foreground">Update filmstock information</p>
        </div>

        <FilmstockForm filmstock={filmstock} />
      </main>
    </div>
  )
}
