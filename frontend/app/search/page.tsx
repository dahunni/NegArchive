import { redirect } from "next/navigation"

/** Search is the filter bar on the roll list now; the query survives the redirect. */
export default async function SearchPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string }>
}) {
  const { q } = await searchParams
  redirect(q ? `/?q=${encodeURIComponent(q)}` : "/")
}
