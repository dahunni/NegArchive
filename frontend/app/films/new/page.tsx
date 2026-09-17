import { redirect } from "next/navigation"

/** Creating a roll is a wizard dialog on the roll list now, not a form page. */
export default function NewFilmPage() {
  redirect("/?new=1")
}
