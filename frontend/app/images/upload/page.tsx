import { Navigation } from "@/components/navigation"
import { ImageUploadForm } from "@/components/image-upload-form"
import { Button } from "@/components/ui/button"
import Link from "next/link"
import { ArrowLeft } from "lucide-react"

export default function UploadImagePage() {
  return (
    <div className="min-h-screen bg-background">
      <Navigation />
      <main className="mx-auto max-w-3xl px-4 py-8 sm:px-6 lg:px-8">
        <div className="mb-6">
          <Button variant="outline" size="sm" asChild>
            <Link href="/images">
              <ArrowLeft className="mr-2 h-4 w-4" />
              Back to Images
            </Link>
          </Button>
        </div>

        <div className="mb-8">
          <h1 className="text-3xl font-bold">Upload Image</h1>
          <p className="mt-1 text-muted-foreground">Upload a new scan or contact sheet</p>
        </div>

        <ImageUploadForm />
      </main>
    </div>
  )
}
