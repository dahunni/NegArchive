import { redirect } from "next/navigation"

/** The separate edit page is gone: the viewer edits the metadata beside the image. */
export default async function EditFramePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  redirect(`/images/${id}`)
}
