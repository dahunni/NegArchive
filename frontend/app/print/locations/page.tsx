import { type Location, getLocations } from "@/lib/api"
import { publicBase } from "@/components/print/data"
import { PrintFrame } from "@/components/print/print-frame"

function Tree({ nodes, parent }: { nodes: Location[]; parent: number | null }) {
  const list = nodes.filter((n) => n.parent_id === parent).sort((a, b) => a.sort_order - b.sort_order || a.id - b.id)
  if (list.length === 0) return null
  return (
    <ul className={parent === null ? "tree" : undefined}>
      {list.map((node) => (
        <li key={node.id}>
          <span className="mono" style={{ fontWeight: 600 }}>
            {node.code ?? ""}
          </span>{" "}
          {node.name}
          <span className="meta">
            {" "}
            · {node.kind} · {node.rolls_in_subtree} roll{node.rolls_in_subtree === 1 ? "" : "s"} · LOC-{node.id}
          </span>
          {node.kind !== "sleeve" ? <Tree nodes={nodes} parent={node.id} /> : null}
        </li>
      ))}
    </ul>
  )
}

/** The whole storage tree on paper (M4), for the door of the archive. */
export default async function LocationsPrintPage() {
  const [locations, base] = await Promise.all([getLocations(), publicBase()])
  const sleeves = locations.filter((n) => n.kind === "sleeve").length
  return (
    <PrintFrame title="Storage tree">
      <section className="sheet" data-testid="tree-sheet">
        <div className="title">Where the negatives are</div>
        <div className="meta">
          {locations.length - sleeves} locations, {sleeves} sleeve pages · printed {new Date().toLocaleDateString()} · {base}
        </div>
        <hr className="hr" />
        <Tree nodes={locations} parent={null} />
      </section>
    </PrintFrame>
  )
}
