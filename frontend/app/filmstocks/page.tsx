import { redirect } from "next/navigation"

/** Cameras, lenses and film stocks are one "Gear" section with tabs since M1. */
export default function FilmstocksPage() {
  redirect("/gear?tab=filmstocks")
}
