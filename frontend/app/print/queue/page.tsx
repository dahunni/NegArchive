import { PRINT_QUEUE_PAGE, getPrintQueue } from "@/lib/api"
import { PrintQueueView } from "@/components/print-queue"

export const metadata = { title: "Print queue — NegArchive" }

/** The first page of the queue, rendered on the server; the rest loads on demand. */
export default async function PrintQueuePage() {
  const queue = await getPrintQueue({ limit: PRINT_QUEUE_PAGE })
  return <PrintQueueView queue={queue} />
}
