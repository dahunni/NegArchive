import { SettingsWorkspace } from "@/components/settings-workspace"

/**
 * Settings is a client page on purpose (roadmap M3): everything on it — the
 * library folders, the watch state, the import report — changes while you are
 * looking at it, and it has to keep working when the roll list does not, because
 * this is also where you come to find out *why* the archive is unhappy.
 */
export const metadata = {
  title: "Settings — NegArchive",
}

export default function SettingsPage() {
  return <SettingsWorkspace />
}
