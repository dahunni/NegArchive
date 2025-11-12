import { Navigation } from "@/components/navigation"
import { FilmForm } from "@/components/film-form"
import { Button } from "@/components/ui/button"
import Link from "next/link"
import { ArrowLeft } from "lucide-react"

export default function NewFilmPage() {
  return (
    <div className="min-h-screen bg-background">
      <Navigation />
      <main className="mx-auto max-w-3xl px-4 py-8 sm:px-6 lg:px-8">
        <div className="mb-6">
          <Button variant="outline" size="sm" asChild>
            <Link href="/films">
              <ArrowLeft className="mr-2 h-4 w-4" />
              Back to Films
            </Link>
          </Button>
        </div>

        <div className="mb-8">
          <h1 className="text-3xl font-bold">New Film</h1>
          <p className="mt-1 text-muted-foreground">Create a new film roll in your archive</p>
        </div>

        <FilmForm />
      </main>
    </div>
  )
}
