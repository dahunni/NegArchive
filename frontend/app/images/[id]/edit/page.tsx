import { getImage } from "@/lib/api"
import { Navigation } from "@/components/navigation"
import { ImageEditForm } from "@/components/image-edit-form"
import { Button } from "@/components/ui/button"
import Link from "next/link"
import { ArrowLeft } from "lucide-react"

export default async function EditImagePage({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = await params
  const image = await getImage(Number(id))

  return (
    <div className="min-h-screen bg-background">
      <Navigation />
      <main className="mx-auto max-w-3xl px-4 py-8 sm:px-6 lg:px-8">
        <div className="mb-6">
          <Button variant="outline" size="sm" asChild>
            <Link href={`/images/${id}`}>
              <ArrowLeft className="mr-2 h-4 w-4" />
              Back to Image
            </Link>
          </Button>
        </div>

        <div className="mb-8">
          <h1 className="text-3xl font-bold">Edit Image</h1>
          <p className="mt-1 text-muted-foreground">Update image metadata and information</p>
        </div>

        <ImageEditForm image={image} />
      </main>
    </div>
  )
}
