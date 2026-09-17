import { getPrintQueue } from "@/lib/api"
import { PrintQueueView } from "@/components/print-queue"

export const metadata = { title: "Print queue — NegArchive" }

export default async function PrintQueuePage() {
  const queue = await getPrintQueue()
  return <PrintQueueView queue={queue} />
}
