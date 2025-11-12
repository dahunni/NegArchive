import { getLenses } from "@/lib/api"
import { Navigation } from "@/components/navigation"
import { CatalogList } from "@/components/catalog-list"
import { Button } from "@/components/ui/button"
import Link from "next/link"
import { Plus } from "lucide-react"

export default async function LensesPage() {
  const lenses = await getLenses()

  return (
    <div className="min-h-screen bg-background">
      <Navigation />
      <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        <div className="mb-8 flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold">Lenses</h1>
            <p className="mt-1 text-muted-foreground">Manage your lens equipment catalog</p>
          </div>
          <Button asChild>
            <Link href="/lenses/new">
              <Plus className="mr-2 h-4 w-4" />
              New Lens
            </Link>
          </Button>
        </div>
        <CatalogList items={lenses} type="lens" />
      </main>
    </div>
  )
}
