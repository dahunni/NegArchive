import { type Location, getLocations } from "@/lib/api"
import { publicBase } from "@/components/print/data"
import { PrintFrame } from "@/components/print/print-frame"
import { PrintedOn } from "@/app/print/printed-on"

/** How many tree rows fit under the header on one A4 sheet. */
const ROWS_PER_SHEET = 42

/** How far one level of the tree is indented. */
const INDENT_MM = 6

interface Row {
  node: Location
  depth: number
}

/**
 * The tree, depth first, as a flat list of rows.
 *
 * Flat because the printout is paginated: a nested `<ul>` cannot be cut in half
 * across two sheets, and a `.sheet` clips whatever does not fit. The depth is
 * carried along and drawn as an indent, so the shape survives the flattening.
 */
function flatten(nodes: Location[], parent: number | null, depth: number): Row[] {
  return nodes
    .filter((n) => n.parent_id === parent)
    .sort((a, b) => a.sort_order - b.sort_order || a.id - b.id)
    .flatMap((node) => [
      { node, depth },
      ...(node.kind !== "sleeve" ? flatten(nodes, node.id, depth + 1) : []),
    ])
}

/** The whole storage tree on paper (M4), for the door of the archive. */
export default async function LocationsPrintPage() {
  const [locations, base] = await Promise.all([getLocations(), publicBase()])
  const sleeves = locations.filter((n) => n.kind === "sleeve").length
  const rows = flatten(locations, null, 0)
  const sheets: Row[][] = []
  for (let i = 0; i < Math.max(rows.length, 1); i += ROWS_PER_SHEET) sheets.push(rows.slice(i, i + ROWS_PER_SHEET))
  return (
    <PrintFrame title="Storage tree">
      {sheets.map((chunk, index) => (
        <section key={index} className="sheet" data-testid="tree-sheet">
          <div className="title">Where the negatives are</div>
          <div className="meta">
            {locations.length - sleeves} locations, {sleeves} sleeve pages · sheet {index + 1} of {sheets.length} ·{" "}
            <PrintedOn /> · {base}
          </div>
          <hr className="hr" />
          <ul className="tree">
            {chunk.map(({ node, depth }) => (
              <li key={node.id} style={{ marginLeft: `${depth * INDENT_MM}mm` }}>
                <span className="mono" style={{ fontWeight: 600 }}>
                  {node.code ?? ""}
                </span>{" "}
                {node.name}
                <span className="meta">
                  {" "}
                  · {node.kind} · {node.rolls_in_subtree} roll{node.rolls_in_subtree === 1 ? "" : "s"} · LOC-{node.id}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </PrintFrame>
  )
}
