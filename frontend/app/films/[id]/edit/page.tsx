import { redirect } from "next/navigation"

/** Editing a roll is a side panel on the roll page now, not its own page. */
export default async function EditFilmPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  redirect(`/films/${id}?edit=1`)
}
