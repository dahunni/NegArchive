import { getLens } from "@/lib/api"
import { Navigation } from "@/components/navigation"
import { CatalogForm } from "@/components/catalog-form"
import { Button } from "@/components/ui/button"
import Link from "next/link"
import { ArrowLeft } from "lucide-react"

export default async function EditLensPage({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = await params
  const lens = await getLens(Number(id))

  return (
    <div className="min-h-screen bg-background">
      <Navigation />
      <main className="mx-auto max-w-3xl px-4 py-8 sm:px-6 lg:px-8">
        <div className="mb-6">
          <Button variant="outline" size="sm" asChild>
            <Link href="/lenses">
              <ArrowLeft className="mr-2 h-4 w-4" />
              Back to Lenses
            </Link>
          </Button>
        </div>

        <div className="mb-8">
          <h1 className="text-3xl font-bold">Edit Lens</h1>
          <p className="mt-1 text-muted-foreground">Update lens information</p>
        </div>

        <CatalogForm type="lens" item={lens} />
      </main>
    </div>
  )
}
