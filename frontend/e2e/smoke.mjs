/**
 * End-to-end smoke test for the M1 UI.
 *
 * It drives a real browser against a running backend and frontend and walks the
 * workflow the rework is built around: find a roll, create one, dump scans in,
 * number a frame, look at it, file it. Every route is visited at desktop width and
 * at 375px, and any console error fails the run.
 *
 *   # backend on :8010 (see README), frontend on :3010
 *   npm run e2e
 *   BASE_URL=http://localhost:3000 npm run e2e          # against `next dev`
 *   SCREENSHOT_DIR=../screenshots npm run e2e           # refresh the README shots
 */

import { chromium } from "playwright"
import { mkdir, writeFile } from "node:fs/promises"
import { tmpdir } from "node:os"
import path from "node:path"

const BASE_URL = process.env.BASE_URL || "http://localhost:3010"
const SHOT_DIR = process.env.SCREENSHOT_DIR || ""
const DESKTOP = { width: 1440, height: 900 }
const MOBILE = { width: 375, height: 812 }
/** Debounce (250 ms) plus a round trip to the API, with room to spare. */
const FILTER_MS = 900

const failures = []
const notes = []

/** True when the locator becomes visible within the timeout, false otherwise. */
async function visible(locator, timeout = 15000) {
  try {
    await locator.first().waitFor({ state: "visible", timeout })
    return true
  } catch {
    return false
  }
}

/**
 * Click and wait for what the click should produce. Retried once, because a click
 * that lands between first paint and hydration does nothing at all.
 */
async function clickUntil(trigger, target, attempts = 4) {
  for (let attempt = 0; attempt < attempts; attempt++) {
    await trigger.click()
    if (await visible(target, 2500)) return true
  }
  return false
}

function check(label, condition, detail = "") {
  if (condition) {
    notes.push(`  ok    ${label}`)
  } else {
    failures.push(`${label}${detail ? ` — ${detail}` : ""}`)
    notes.push(`  FAIL  ${label}${detail ? ` — ${detail}` : ""}`)
  }
}

/** A 2x1 JPEG is enough: the backend re-encodes everything for the preview anyway. */
const SAMPLE_JPEG = Buffer.from(
  "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0a" +
    "HBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIy" +
    "MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAIDASIA" +
    "AhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQA" +
    "AAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3" +
    "ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWm" +
    "p6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEA" +
    "AwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSEx" +
    "BhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElK" +
    "U1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3" +
    "uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD3+iii" +
    "gD//2Q==",
  "base64",
)

/**
 * The same JPEG with a NegPy XMP packet spliced in (M5).
 *
 * XMP lives in a JPEG APP1 segment: marker FF E1, a two-byte length, the
 * namespace string "http://ns.adobe.com/xap/1.0/\0" and then the packet. Writing
 * it by hand here keeps the e2e run free of an image library, and it is exactly
 * what the backend has to read back out.
 */
function jpegWithNegpyXmp(properties) {
  const attributes = Object.entries(properties)
    .map(([key, value]) => `negpy:${key}="${value}"`)
    .join(" ")
  const packet = Buffer.from(
    `<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>` +
      `<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">` +
      `<rdf:Description rdf:about="" xmlns:negpy="https://negpy.app/ns/1.0/" ${attributes}/>` +
      `</rdf:RDF></x:xmpmeta><?xpacket end="w"?>`,
    "utf-8",
  )
  const header = Buffer.from("http://ns.adobe.com/xap/1.0/\0", "binary")
  const length = header.length + packet.length + 2
  const segment = Buffer.concat([
    Buffer.from([0xff, 0xe1, (length >> 8) & 0xff, length & 0xff]),
    header,
    packet,
  ])
  return Buffer.concat([SAMPLE_JPEG.subarray(0, 2), segment, SAMPLE_JPEG.subarray(2)])
}

async function sampleFiles() {
  const dir = path.join(tmpdir(), `negarchive-e2e-${Date.now()}`)
  await mkdir(dir, { recursive: true })
  const paths = []
  for (const name of ["E2E_001.jpg", "E2E_002.jpg"]) {
    const file = path.join(dir, name)
    await writeFile(file, SAMPLE_JPEG)
    paths.push(file)
  }
  return paths
}

/** Console errors and uncaught exceptions are collected for the whole run. */
function watchConsole(page, sink) {
  page.on("console", (message) => {
    if (message.type() === "error") sink.push(`console: ${message.text()}`)
  })
  page.on("pageerror", (error) => sink.push(`pageerror: ${error.message}`))
  page.on("requestfailed", (request) => {
    // navigations that were cancelled by a client-side redirect are not failures
    if (request.failure()?.errorText === "net::ERR_ABORTED") return
    sink.push(`requestfailed: ${request.url()} (${request.failure()?.errorText})`)
  })
}

/**
 * Open a roll that actually has frames in it, so the screenshots show a real
 * workspace rather than the two-frame roll this script just created.
 */
async function openFullestRoll(p) {
  const rows = p.getByTestId("roll-row")
  await rows.first().waitFor()
  const counts = await rows.evaluateAll((nodes) =>
    nodes.map((node) => Number(node.getAttribute("data-frames") || 0)),
  )
  const best = counts.indexOf(Math.max(...counts))
  await rows.nth(Math.max(best, 0)).getByTestId("roll-title").click()
  await p.waitForLoadState("load")
}

/** Wait until every <img> on the page has actually decoded, so shots are not blank. */
async function settleImages(page, timeout = 10000) {
  await page
    .waitForFunction(
      () => Array.from(document.images).every((img) => img.complete && img.naturalWidth > 0),
      undefined,
      { timeout },
    )
    .catch(() => {})
}

async function shot(page, index, name) {
  if (!SHOT_DIR) return
  await page.waitForTimeout(500) // let dialog/sheet animations finish
  await settleImages(page)
  await mkdir(SHOT_DIR, { recursive: true })
  await page.screenshot({ path: path.join(SHOT_DIR, `screenshot-${String(index).padStart(2, "0")}.png`) })
  notes.push(`  shot  ${index} ${name}`)
}

async function main() {
  const browser = await chromium.launch()
  const consoleErrors = []
  const context = await browser.newContext({ viewport: DESKTOP })
  const page = await context.newPage()
  watchConsole(page, consoleErrors)

  // ---------------------------------------------------------------- roll list
  await page.goto(BASE_URL, { waitUntil: "load" })
  check("home page shows the roll list", await visible(page.getByTestId("roll-list")))
  const rollsBefore = await page.getByTestId("roll-row").count()
  check("home page lists rolls", rollsBefore > 0, `${rollsBefore} rows`)
  check(
    "roll rows carry real thumbnails",
    (await page.locator('[data-testid="roll-row"] img').count()) > 0,
  )
  await shot(page, 1, "roll list")

  // filters. M3 moved the filtering into Postgres, so this is a debounced round
  // trip to the API rather than an array filter: give it time to come back.
  await page.getByTestId("roll-search").first().fill("harbour")
  await page.waitForTimeout(FILTER_MS)
  const narrowed = await page.getByTestId("roll-row").count()
  check("the search filter narrows the list", narrowed < rollsBefore, `${narrowed} of ${rollsBefore}`)
  check("the search is server-side", narrowed > 0, "seeded archive has 'harbour' rolls")
  await page.getByTestId("roll-search").first().fill("")
  await page.waitForTimeout(FILTER_MS)

  // /films renders the same page
  await page.goto(`${BASE_URL}/films`, { waitUntil: "load" })
  check("/films still works", await visible(page.getByTestId("roll-list")))

  // M7: the search palette — ⌘K from anywhere, everything grouped, Enter opens
  await page.goto(`${BASE_URL}/gear`, { waitUntil: "load" })
  await page.keyboard.press("ControlOrMeta+k")
  check("M7: ⌘K opens the search palette", await visible(page.getByTestId("search-palette")))
  await page.getByTestId("search-input").fill("harbour")
  await page.waitForTimeout(FILTER_MS)
  const hitKinds = await page.getByTestId("search-result").evaluateAll((nodes) => nodes.map((n) => n.getAttribute("data-kind")))
  check("M7: the palette finds rolls", hitKinds.includes("roll"), hitKinds.join(","))
  check("M7: the palette finds frames", hitKinds.includes("frame"), hitKinds.join(","))
  const firstHit = ((await page.getByTestId("search-result").first().textContent()) || "").toLowerCase()
  check("M7: the best match comes first", firstHit.includes("harbour"), firstHit.slice(0, 60))
  await page.getByTestId("search-input").fill("harbor")
  await page.waitForTimeout(FILTER_MS)
  check("M7: a typo still finds the roll", (await page.getByTestId("search-result").count()) > 0)
  await page.getByTestId("search-input").fill("camera:nikon")
  await page.waitForTimeout(FILTER_MS)
  // Only the roll rows say which camera they were shot on; a frame row names its roll.
  const qualified = await page
    .locator('[data-testid="search-result"][data-kind="roll"]')
    .evaluateAll((nodes) => nodes.map((n) => (n.textContent || "").toLowerCase()))
  check("M7: a qualifier narrows to one field", qualified.length > 0 && qualified.every((t) => t.includes("nikon")), qualified.slice(0, 3).join(" | "))
  await page.getByTestId("search-input").fill("harbour")
  await page.waitForTimeout(FILTER_MS)
  await page.keyboard.press("Enter")
  await page.waitForURL(/\/films\/\d+/, { timeout: 8000 }).catch(() => {})
  check("M7: Enter opens the first result", new URL(page.url()).pathname.startsWith("/films/"), page.url())
  // The dialog fades out; wait for it to leave the DOM before typing again, or the
  // `/` lands in its input.
  await page.getByTestId("search-palette").waitFor({ state: "detached", timeout: 5000 }).catch(() => {})
  check("M7: the palette closed on navigation", (await page.getByTestId("search-palette").count()) === 0)
  await page.keyboard.press("/")
  check("M7: / opens the palette off the roll list", await visible(page.getByTestId("search-palette")))
  check("M7: the palette remembers recent searches", await visible(page.getByTestId("search-recent")))
  await page.keyboard.press("Escape")
  await page.goto(`${BASE_URL}/images?q=harbour`, { waitUntil: "load" })
  // The streamed page can briefly hold the input twice (the hidden placeholder and
  // the real one): wait for the visible one.
  await visible(page.getByTestId("frame-search"))
  check(
    "M7: the frames page takes ?q=",
    ((await page.getByTestId("frame-search").first().inputValue()) || "") === "harbour",
  )

  // /search redirects into the filtered roll list
  await page.goto(`${BASE_URL}/search?q=kyoto`, { waitUntil: "load" })
  check("/search redirects to the roll list", new URL(page.url()).pathname === "/")
  check("/search keeps the query", new URL(page.url()).searchParams.get("q") === "kyoto")

  // ---------------------------------------------------------------- wizard
  await page.goto(BASE_URL, { waitUntil: "load" })
  check(
    "the New roll button opens the wizard",
    await clickUntil(page.getByTestId("new-roll"), page.getByTestId("roll-wizard")),
  )
  await shot(page, 6, "new roll wizard")

  // validation: the wizard refuses an untitled roll
  await page.getByRole("button", { name: "Next" }).click()
  check("the wizard refuses an untitled roll", await visible(page.getByRole("alert")))

  const title = `E2E roll ${Date.now()}`
  await page.locator("#wizard-title").fill(title)
  await page.locator("#wizard-start").fill("2024-09-01")
  await page.locator("#wizard-end").fill("2024-09-04")
  await page.getByRole("button", { name: "Next" }).click()
  await page.locator("#wizard-camera").click()
  await page.getByRole("option", { name: "Nikon F5", exact: true }).click()
  await page.getByRole("button", { name: "Next" }).click()
  // M4: storage is a location picker plus the serial; leave the serial empty so the
  // API allocates one, and check it did further down.
  await page.getByRole("button", { name: "Create roll" }).click()

  // ---------------------------------------------------------------- upload
  const files = await sampleFiles()
  await page.getByTestId("upload-input").setInputFiles(files)
  await page.waitForTimeout(1500)
  check(
    "both files uploaded from the wizard's drop zone",
    (await page.getByTestId("upload-queue").locator("li").count()) === 2,
  )
  await page.getByRole("button", { name: "Open roll" }).click()
  await page.waitForLoadState("load")
  check("the wizard lands on the new roll", await visible(page.getByText(title).first()))
  const serialText = ((await page.getByTestId("roll-serial").textContent().catch(() => "")) || "").trim()
  check("M4: the roll got a NEG-YYYY-NNNN serial", /^[A-Z0-9]+-\d{4}-\d{4,}$/.test(serialText), serialText || "none")
  check("M4: the lifecycle stepper is on the roll page", await visible(page.getByTestId("status-stepper")))
  check("M4: frames show their strip and position", await visible(page.getByTestId("frame-position")))
  // Wait for the first cell rather than counting straight after `load`: the grid
  // is rendered from a server round trip, and on a cold service worker the
  // navigation can paint before it comes back.
  await visible(page.getByTestId("frame-cell"))
  check(
    "the uploaded frames are in the grid",
    (await page.getByTestId("frame-cell").count()) === 2,
    `${await page.getByTestId("frame-cell").count()} cells`,
  )

  // M2 numbers the frames from their filenames (E2E_001.jpg -> 1), so the grid
  // arrives already in frame order instead of showing "unnumbered".
  check(
    "the frame numbers came from the filenames",
    (await page.getByTestId("frame-number-input").evaluateAll((inputs) =>
      inputs.map((input) => input.value).join(","),
    )) === "1,2",
  )
  check(
    "the original filename is in the viewer's panel",
    await page
      .getByTestId("frame-cell")
      .first()
      .click()
      .then(() => page.getByTestId("viewer-original-filename").textContent())
      .then((text) => (text || "").startsWith("E2E_00")),
  )
  await page.keyboard.press("Escape")

  // gear was remembered for next time — as catalog ids since M2 (R#14)
  const remembered = await page.evaluate(() =>
    window.localStorage.getItem("negarchive.lastGear.v2"),
  )
  check(
    "the wizard remembers the last gear",
    /"camera_id":"\d+"/.test(remembered || ""),
    remembered ?? "null",
  )

  // ---------------------------------------------------------------- inline edit
  // The grid is sorted by frame number, so an edited frame moves; look it up by
  // value rather than by position.
  const numbers = () =>
    page.getByTestId("frame-number-input").evaluateAll((inputs) => inputs.map((i) => i.value))
  const firstNumber = page.getByTestId("frame-number-input").first()
  await firstNumber.fill("17")
  await firstNumber.press("Enter")
  await page.waitForTimeout(700)
  await page.reload({ waitUntil: "load" })
  check("an inline frame number survives a reload", (await numbers()).includes("17"))
  check("the grid re-sorted after the change", (await numbers()).join(",") === "2,17")

  // M7: renumber the roll in one go — the dialog previews, Apply writes
  check("M7: the roll page offers Renumber", await visible(page.getByTestId("renumber-roll")))
  check(
    "M7: Renumber opens a dialog with a plan",
    await clickUntil(page.getByTestId("renumber-roll").first(), page.getByTestId("renumber-plan")),
  )
  const planText = (await page.getByTestId("renumber-plan").textContent()) || ""
  check("M7: the plan shows old → new", planText.includes("17") && planText.includes("2"), planText.slice(0, 80))
  await page.getByTestId("renumber-apply").click()
  await page.waitForTimeout(1500)
  check("M7: the frames are 1, 2 after renumbering", (await numbers()).join(",") === "1,2", (await numbers()).join(","))
  // …and a selection can be shifted on its own
  await page.getByLabel("Select frame 2").first().click()
  check("M7: the bulk bar offers Renumber…", await visible(page.getByTestId("bulk-renumber")))
  await page.getByTestId("bulk-renumber").click()
  await page.getByTestId("renumber-mode-shift").click()
  await page.getByTestId("renumber-offset").fill("10")
  await page.waitForTimeout(FILTER_MS)
  check("M7: shifting previews 2 → 12", ((await page.getByTestId("renumber-plan").textContent()) || "").includes("12"))
  await page.getByTestId("renumber-apply").click()
  await page.waitForTimeout(1500)
  check("M7: only the selected frame moved", (await numbers()).join(",") === "1,12", (await numbers()).join(","))
  await page.keyboard.press("Escape")

  const firstNote = page.getByTestId("frame-notes-input").first()
  await firstNote.fill("e2e note")
  await firstNote.press("Enter")
  await page.waitForTimeout(700)
  await page.reload({ waitUntil: "load" })
  check(
    "an inline note survives a reload",
    (
      await page.getByTestId("frame-notes-input").evaluateAll((inputs) =>
        inputs.map((input) => input.value),
      )
    ).includes("e2e note"),
  )

  // ---------------------------------------------------------------- bulk bar
  // The first checkbox *in the grid*: the page has one above it now ("These are
  // finished positives", M6.1), and that one selects nothing.
  await page.getByTestId("frame-grid").getByRole("checkbox").first().click()
  check("selecting a frame opens the bulk bar", await visible(page.getByTestId("bulk-bar")))
  await page.getByRole("button", { name: "Clear" }).click()

  // ---------------------------------------------------------------- keyboard
  const cells = page.getByTestId("frame-cell")
  await cells.first().focus()
  await page.keyboard.press("ArrowRight")
  const focusedLabel = await page.evaluate(() => document.activeElement?.getAttribute("aria-label"))
  check("arrow keys move between frames", (focusedLabel || "").startsWith("Frame"), focusedLabel ?? "none")
  await page.keyboard.press("Enter")
  await page.getByTestId("frame-viewer").waitFor()
  check("Enter opens the viewer", await visible(page.getByTestId("frame-viewer")))
  await page.keyboard.press("Escape")
  await page.getByTestId("frame-viewer").waitFor({ state: "hidden" })
  check("Escape closes the viewer", (await page.getByTestId("frame-viewer").count()) === 0)

  // ---------------------------------------------------------------- roll workspace shot
  await page.goto(`${BASE_URL}/films`, { waitUntil: "load" })
  await openFullestRoll(page)
  check("a roll opens as a workspace", await visible(page.getByTestId("frame-grid")))
  check("the contact sheet sits on top", await visible(page.getByText("Contact sheet").first()))
  await shot(page, 2, "roll workspace")

  // ---------------------------------------------------------------- viewer
  await page.getByTestId("frame-thumb").first().click()
  await page.getByTestId("frame-viewer").waitFor()
  const firstSrc = await page.getByTestId("viewer-image").getAttribute("src")
  await page.getByTestId("viewer-next").click()
  await page.waitForTimeout(400)
  const secondSrc = await page.getByTestId("viewer-image").getAttribute("src")
  check("next moves to another frame", firstSrc !== secondSrc, `${firstSrc} vs ${secondSrc}`)
  await page.keyboard.press("ArrowLeft")
  await page.waitForTimeout(400)
  check(
    "the left arrow key goes back",
    (await page.getByTestId("viewer-image").getAttribute("src")) === firstSrc,
  )
  await page.getByRole("button", { name: "Zoom in" }).click()
  check("zoom works", (await page.getByTestId("viewer-zoom").textContent())?.trim() === "150%")
  await page.getByRole("button", { name: "Fit to screen" }).click()
  check(
    "the metadata panel edits in place",
    await visible(page.getByTestId("viewer-frame-number")),
  )
  await shot(page, 3, "frame viewer")
  await page.keyboard.press("Escape")

  // ---------------------------------------------------------------- other routes
  await page.goto(`${BASE_URL}/gear`, { waitUntil: "load" })
  check("the gear section lists the catalog", await visible(page.getByTestId("gear-list")))
  await page.getByRole("tab", { name: /Film stocks/ }).click()
  check("gear tabs switch", await visible(page.getByTestId("gear-list")))
  await shot(page, 7, "gear")

  for (const [from, to] of [
    ["/cameras", "/gear"],
    ["/lenses", "/gear"],
    ["/filmstocks", "/gear"],
    ["/images/upload", "/images"],
  ]) {
    await page.goto(BASE_URL + from, { waitUntil: "load" })
    check(`${from} redirects to ${to}`, new URL(page.url()).pathname === to, page.url())
  }

  await page.goto(`${BASE_URL}/films/new`, { waitUntil: "load" })
  check("/films/new opens the wizard", await visible(page.getByTestId("roll-wizard")))
  await page.waitForTimeout(200)
  await page.keyboard.press("Escape")

  // a frame URL opens the viewer; the edit URL redirects to it
  const frameId = await page.evaluate(async () => {
    const res = await fetch("/api/images?type=scan")
    const items = await res.json()
    return items[0]?.id
  })
  await page.goto(`${BASE_URL}/images/${frameId}/edit`, { waitUntil: "load" })
  check(
    "/images/{id}/edit redirects to the viewer",
    new URL(page.url()).pathname === `/images/${frameId}`,
    page.url(),
  )
  check("/images/{id} opens the viewer", await visible(page.getByTestId("frame-viewer")))
  await page.keyboard.press("Escape")

  await page.goto(`${BASE_URL}/images`, { waitUntil: "load" })
  check("the frames page lists frames", await visible(page.getByTestId("frame-grid")))

  // ---------------------------------------------------------------- M3: paging
  await page.goto(BASE_URL, { waitUntil: "load" })
  const pagedRolls = await page.evaluate(async () => {
    const res = await fetch("/api/films?limit=2")
    return res.json()
  })
  check("the roll list is paginated", typeof pagedRolls.total === "number", JSON.stringify(pagedRolls).slice(0, 120))
  check("a page is capped at the limit", (pagedRolls.items || []).length <= 2)
  check(
    "an unpaged request is still a bare array",
    Array.isArray(await page.evaluate(() => fetch("/api/films").then((r) => r.json()))),
  )

  // ---------------------------------------------------------------- M3: LAN footer
  check("the footer shows the LAN address", await visible(page.getByTestId("lan-footer")))
  check("M7: the footer shows the version", await visible(page.getByTestId("app-version")))
  const footerVersion = ((await page.getByTestId("app-version").first().textContent()) || "").trim()
  const apiVersion = await page.evaluate(async () => (await (await fetch("/api/system/version")).json()).version)
  check("M7: the footer's version is the backend's", footerVersion === `v${apiVersion}`, `${footerVersion} vs ${apiVersion}`)
  check(
    "M7: the footer opens what's new",
    await clickUntil(page.getByTestId("whats-new-open").first(), page.getByTestId("whats-new")),
  )
  await page.keyboard.press("Escape")
  await page.waitForTimeout(300)

  // M7: an update is noticed. Pretend this browser last saw an older version and reload.
  await page.evaluate(() => window.localStorage.setItem("negarchive.version.seen", "0.0.1"))
  await page.reload({ waitUntil: "load" })
  check("M7: the first load after an update opens what's new", await visible(page.getByTestId("whats-new")))
  const updateTitle = (await page.getByTestId("whats-new").textContent()) || ""
  check("M7: the update dialog names the new version", updateTitle.includes(`updated to v${apiVersion}`), updateTitle.slice(0, 80))
  await page.getByTestId("whats-new-close").click()
  await page.waitForTimeout(300)
  const seenAfter = await page.evaluate(() => window.localStorage.getItem("negarchive.version.seen"))
  check("M7: closing the dialog marks the version seen", seenAfter === apiVersion, String(seenAfter))
  await page.reload({ waitUntil: "load" })
  await page.waitForTimeout(800)
  check("M7: it does not open again", (await page.getByTestId("whats-new").count()) === 0)
  const lanUrl = await page.getByTestId("lan-url").textContent()
  check("the LAN address looks like a URL", /^https?:\/\/.+:\d+$/.test((lanUrl || "").trim()), lanUrl ?? "none")
  await page.getByTestId("lan-qr-toggle").click()
  check("the QR code appears", await visible(page.getByTestId("lan-qr")))
  const qrOk = await page.evaluate(async () => {
    const res = await fetch("/api/system/qr.svg")
    const body = await res.text()
    return res.ok && body.includes("<svg") && body.includes("currentColor")
  })
  check("the QR code is a themed SVG from the backend", qrOk)

  // ---------------------------------------------------------------- M3: settings
  await page.goto(`${BASE_URL}/settings`, { waitUntil: "load" })
  check("the settings page renders", await visible(page.getByTestId("settings")))
  check("the watch folder toggle is there", await visible(page.getByTestId("watch-toggle")))
  check("the watch readout is there", await visible(page.getByTestId("watch-readout")))
  check("the export links are there", await visible(page.getByTestId("export-zip")))

  // M7: the version on screen, in Settings and in the footer, and the changelog behind it
  check("M7: Settings has an About card", await visible(page.getByTestId("about")))
  const aboutText = (await page.getByTestId("about").first().textContent()) || ""
  check("M7: About shows a version number", /v\d+\.\d+\.\d+/.test(aboutText), aboutText.slice(0, 80))
  check(
    "M7: About opens the changelog",
    await clickUntil(page.getByTestId("about-whats-new").first(), page.getByTestId("changelog")),
  )
  const entries = await page.getByTestId("changelog-entry").count()
  check("M7: the changelog lists releases", entries >= 2, `${entries} entries`)
  await page.getByTestId("whats-new-close").click()
  await page.waitForTimeout(300)
  check("M7: the changelog closes", (await page.getByTestId("whats-new").count()) === 0)
  const csvOk = await page.evaluate(async () => {
    const res = await fetch("/api/export/rolls.csv")
    const body = await res.text()
    return res.ok && body.startsWith("id,archive_serial,title,camera")
  })
  check("the roll CSV downloads", csvOk)
  await shot(page, 9, "settings")

  // ---------------------------------------------------------------- M3: PWA
  await page.goto(BASE_URL, { waitUntil: "load" })
  const manifestHref = await page.getAttribute('link[rel="manifest"]', "href")
  check("the page links a manifest", manifestHref === "/manifest.webmanifest", manifestHref ?? "none")

  const manifest = await page.evaluate(async () => {
    const res = await fetch("/manifest.webmanifest")
    return res.ok ? res.json() : null
  })
  check("the manifest is served and parses", manifest !== null)
  check("the manifest is installable", manifest?.display === "standalone" && Boolean(manifest?.start_url))
  check(
    "the manifest has a 512px and a maskable icon",
    (manifest?.icons || []).some((i) => i.sizes === "512x512") &&
      (manifest?.icons || []).some((i) => (i.purpose || "").includes("maskable")),
  )
  const iconsOk = await page.evaluate(async (icons) => {
    for (const icon of icons) {
      const res = await fetch(icon.src)
      if (!res.ok) return false
    }
    return true
  }, manifest?.icons || [])
  check("every manifest icon is served", iconsOk)

  const swRegistered = await page.evaluate(async () => {
    if (!("serviceWorker" in navigator)) return "unsupported"
    const registration = await navigator.serviceWorker.getRegistration("/")
    return registration ? registration.scope : "none"
  })
  check("the service worker registers at the root scope", String(swRegistered).endsWith("/"), String(swRegistered))

  const swCached = await page.evaluate(async () => {
    // Give the worker a moment to finish installing and populating the shell.
    await new Promise((resolve) => setTimeout(resolve, 1500))
    const names = await caches.keys()
    if (names.length === 0) return { names, shell: false }
    let shell = false
    for (const name of names) {
      const cache = await caches.open(name)
      if (await cache.match("/")) shell = true
    }
    return { names, shell }
  })
  check("the service worker caches the app shell", swCached.shell, JSON.stringify(swCached.names))

  // ---------------------------------------------------------------- dark mode
  await page.getByTestId("theme-toggle").click()
  await page.waitForTimeout(400)
  let isDark = await page.evaluate(() => document.documentElement.classList.contains("dark"))
  if (!isDark) {
    await page.getByTestId("theme-toggle").click()
    await page.waitForTimeout(400)
    isDark = await page.evaluate(() => document.documentElement.classList.contains("dark"))
  }
  check("the dark mode toggle sets the class", isDark)
  await shot(page, 8, "frames page, dark")
  await page.getByTestId("theme-toggle").click()
  await page.waitForTimeout(200)
  check(
    "the toggle switches back to light",
    await page.evaluate(() => !document.documentElement.classList.contains("dark")),
  )

  // ---------------------------------------------------------------- M4: paper
  // Work lists on the home page
  await page.goto(BASE_URL, { waitUntil: "load" })
  check("M4: the home page shows the work lists", await visible(page.getByTestId("work-lists")))

  // Locations: create a binder with pages through the UI
  await page.goto(`${BASE_URL}/locations`, { waitUntil: "load" })
  check("M4: the locations page renders", await visible(page.getByTestId("new-location")))
  const binderName = `E2E binder ${Date.now()}`
  check(
    "M4: the new location dialog opens",
    await clickUntil(page.getByTestId("new-location"), page.getByTestId("location-dialog")),
  )
  await page.locator("#loc-kind").click()
  await page.getByRole("option", { name: "Binder" }).click()
  await page.locator("#loc-code").fill("E2E")
  await page.getByTestId("location-name").fill(binderName)
  await page.getByTestId("location-save").click()
  await page.waitForTimeout(800)
  check("M4: the binder appears in the tree", await visible(page.getByText(binderName).first()))
  await page.getByText(binderName).first().click()
  await page.waitForLoadState("load")
  check("M4: the location page shows its path", await visible(page.getByTestId("location-path")))
  await page.getByLabel("Pages to add").fill("3")
  await page.getByTestId("add-pages").click()
  await page.waitForTimeout(800)
  check("M4: pages were added to the binder", (await page.getByTestId("binder-page").count()) === 3)
  check("M4: the location has a QR code", await visible(page.getByTestId("location-qr")))
  const binderId = Number(new URL(page.url()).pathname.split("/").pop())

  // Scanner console: look up the roll by typing its serial, then move it by scanning serial + LOC code
  await page.goto(`${BASE_URL}/scan`, { waitUntil: "load" })
  check("M4: the scanner console renders", await visible(page.getByTestId("scan-input")))
  await page.getByTestId("scan-input").fill(serialText)
  await page.keyboard.press("Enter")
  await page.waitForTimeout(1200)
  check("M4: scanning a serial opens the roll", new URL(page.url()).pathname.startsWith("/films/"), page.url())

  await page.goto(`${BASE_URL}/scan`, { waitUntil: "load" })
  await page.getByTestId("mode-move").click()
  await page.getByTestId("scan-input").fill(serialText)
  await page.keyboard.press("Enter")
  await page.waitForTimeout(800)
  check("M4: the move sequence holds the roll", await visible(page.getByTestId("pending-rolls").getByText(serialText)))
  await page.getByTestId("scan-input").fill(`LOC-${binderId}`)
  await page.keyboard.press("Enter")
  await page.waitForTimeout(1200)
  const logText = (await page.getByTestId("scan-log").textContent()) || ""
  check("M4: scanning the binder moved the roll onto a page", /→ .*E2E/.test(logText) && /1 roll/.test(logText), logText.slice(0, 200))

  // The roll page now shows the location and the move history
  await page.goto(`${BASE_URL}/s/${serialText}`, { waitUntil: "load" })
  // The redirect is issued by the server component; on a hard navigation Next can
  // apply it just after `load`, so wait for the URL rather than reading it at once.
  await page.waitForURL(/\/films\/\d+/, { timeout: 8000 }).catch(() => {})
  check("M4: /s/{serial} opens the roll", new URL(page.url()).pathname.startsWith("/films/"), page.url())
  check("M4: the roll shows where it is", ((await page.getByTestId("roll-location").textContent()) || "").includes("E2E"))
  check("M4: sleeved status after the move", (await page.getByTestId("status-sleeved").getAttribute("aria-current")) === "step")

  // The wedge scanner: fast keystrokes anywhere open a roll
  await page.goto(`${BASE_URL}/gear`, { waitUntil: "load" })
  await page.keyboard.type(serialText, { delay: 5 })
  await page.keyboard.press("Enter")
  await page.waitForTimeout(1500)
  check("M4: a wedge scan from any page opens the roll", new URL(page.url()).pathname.startsWith("/films/"), page.url())

  // Printouts render at paper size
  const rollId = Number(new URL(page.url()).pathname.split("/").pop())
  await page.goto(`${BASE_URL}/print/roll/${rollId}`, { waitUntil: "load" })
  check("M4: the cover sheet renders", await visible(page.getByTestId("cover-sheet")))
  const sheetWidth = await page.getByTestId("cover-sheet").evaluate((el) => el.getBoundingClientRect().width)
  check("M4: the cover sheet is A4 wide (210mm ≈ 794px)", Math.abs(sheetWidth - 794) < 6, `${sheetWidth}px`)
  check("M4: the cover sheet carries the serial", ((await page.getByTestId("cover-sheet").textContent()) || "").includes(serialText))
  await page.goto(`${BASE_URL}/print/stickers?ids=${rollId}`, { waitUntil: "load" })
  // `load` can fire while the streamed page body is still in React's hidden
  // placeholder, where every box measures 0×0: wait for it to be laid out.
  check("M4: stickers render", await visible(page.getByTestId("sticker")))
  check("M4: exactly one sticker", (await page.getByTestId("sticker").count()) === 1)
  const stickerBox = await page.getByTestId("sticker").first().evaluate((el) => {
    const r = el.getBoundingClientRect()
    return [r.width, r.height]
  })
  check("M4: a sticker is 50 × 25 mm", Math.abs(stickerBox[0] - 189) < 4 && Math.abs(stickerBox[1] - 94.5) < 4, stickerBox.join("x"))
  await page.goto(`${BASE_URL}/print/location/${binderId}/spine`, { waitUntil: "load" })
  check("M4: the spine label renders", await visible(page.getByTestId("spine-label")))
  await page.goto(`${BASE_URL}/print/location/${binderId}/index`, { waitUntil: "load" })
  check("M4: the binder index renders", await visible(page.getByTestId("index-sheet")))
  await page.goto(`${BASE_URL}/print/commands`, { waitUntil: "load" })
  check("M4: the command cards render", (await page.getByTestId("command-card").count()) >= 8)
  await page.goto(`${BASE_URL}/print/queue`, { waitUntil: "load" })
  check("M4: the print queue lists the new roll", ((await page.getByTestId("print-queue").textContent()) || "").includes(serialText))

  // The queue arrives with nothing selected: "mark printed" freezes a serial, and
  // a button that says "Mark 145 printed" the moment the page loads is one click
  // away from freezing the whole archive.
  check(
    "M4: the queue selects nothing until you do",
    ((await page.getByTestId("mark-all-printed").textContent()) || "").trim() === "Mark printed" &&
      (await page.getByTestId("mark-all-printed").isDisabled()),
  )
  await page.getByTestId("select-shown").click()
  await page.waitForTimeout(300)
  check(
    "M4: selecting the rolls shown arms the button",
    /Mark \d+ printed/.test((await page.getByTestId("mark-all-printed").textContent()) || ""),
    (await page.getByTestId("mark-all-printed").textContent()) || "",
  )
  check("M4: the queue says how many of how many it is showing", await visible(page.getByTestId("queue-count")))
  await page.getByTestId("select-shown").click()

  // Printing an ordinary page: no app chrome, and no row sliced across the break.
  await page.emulateMedia({ media: "print" })
  await page.waitForTimeout(200)
  const printable = await page.evaluate(() => {
    const header = document.querySelector("header")
    const row = document.querySelector('[data-testid="print-queue-list"] > li')
    return {
      headerHidden: !header || getComputedStyle(header).display === "none",
      rowBreak: row ? getComputedStyle(row).breakInside : null,
      background: getComputedStyle(document.body).backgroundColor,
    }
  })
  check("M4: printing a page leaves the navigation off the paper", printable.headerHidden)
  check(
    "M4: a queue row is never split across a page break",
    printable.rowBreak === "avoid",
    printable.rowBreak ?? "none",
  )
  await page.emulateMedia({ media: null })
  await shot(page, 10, "print queue")

  // Load film on a camera creates a roll in status loaded
  await page.goto(`${BASE_URL}/gear`, { waitUntil: "load" })
  check(
    "M4: Load film opens its dialog",
    await clickUntil(page.getByTestId("load-film").first(), page.getByTestId("load-film-dialog")),
  )
  await page.locator("#load-title").fill(`E2E loaded ${Date.now()}`)
  await page.getByTestId("load-film-confirm").click()
  await page.waitForTimeout(1500)
  check("M4: Load film lands on the new roll", new URL(page.url()).pathname.startsWith("/films/"), page.url())
  check("M4: the new roll is in the camera", (await page.getByTestId("status-loaded").getAttribute("aria-current")) === "step")
  const loadedId = Number(new URL(page.url()).pathname.split("/").pop())
  // clean up the loaded roll and the binder through the API
  await page.evaluate(async ({ loadedId, binderId }) => {
    await fetch(`/api/films/${loadedId}`, { method: "DELETE" })
    await fetch(`/api/locations/${binderId}?force=true`, { method: "DELETE" })
  }, { loadedId, binderId })

  // ---------------------------------------------------------------- M5: NegPy
  // A scan that came out of NegPy knows its own roll, frame and date, and brings
  // its `.negpy` sidecar with it. Both go in through the normal bulk upload.
  await page.goto(`${BASE_URL}/films/${rollId}`, { waitUntil: "load" })
  const negpyUpload = await page.evaluate(
    async ({ rollId, jpeg, recipe }) => {
      const bytes = Uint8Array.from(atob(jpeg), (c) => c.charCodeAt(0))
      const body = new FormData()
      body.append("files", new File([bytes], "NEGPY_042.jpg", { type: "image/jpeg" }))
      body.append("files", new File([recipe], "NEGPY_042.jpg.negpy", { type: "application/json" }))
      const res = await fetch(`/api/films/${rollId}/images/bulk`, { method: "POST", body })
      const payload = await res.json()
      return payload.images?.[0] ?? null
    },
    {
      rollId,
      jpeg: jpegWithNegpyXmp({
        CaptureFrame: "42",
        CaptureDate: "2024-09-03",
        CaptureFilmStock: "HP5 Plus",
        Developer: "Rodinal",
        DevelopmentDilution: "1+50",
        DevelopmentTime: "9:30",
        Notes: "From NegPy",
      }).toString("base64"),
      recipe: JSON.stringify({ version: 3, settings: { invert: true, exposure: 0.4, crop: [0, 0, 2, 1] } }),
    },
  )
  check("M5: the file's own XMP set the frame number", negpyUpload?.frame_number === 42, JSON.stringify(negpyUpload?.frame_number))
  check("M5: the capture date came from the file", negpyUpload?.capture_date === "2024-09-03", negpyUpload?.capture_date ?? "none")
  check("M5: the .negpy sidecar was kept", Boolean(negpyUpload?.sidecar_path), negpyUpload?.sidecar_path ?? "none")
  // M6.1: NegPy writes its XMP namespace on export and nowhere else, so a file
  // carrying it is a finished positive — flagged on arrival, never printed again.
  check("M6.1: a file carrying NegPy's XMP comes in as a positive", negpyUpload?.positive === true, String(negpyUpload?.positive))

  await page.reload({ waitUntil: "load" })
  await visible(page.getByTestId("frame-cell"))
  await page.getByTestId("frame-cell").last().click()
  check("M5: the viewer says the frame was edited in NegPy", await visible(page.getByTestId("viewer-negpy")))
  const negpyPanel = (await page.getByTestId("viewer-negpy").textContent()) || ""
  check("M5: the recipe is summarised, not interpreted", /inverted/.test(negpyPanel), negpyPanel.slice(0, 120))
  check("M5: the panel says where the metadata came from", /xmp/.test(negpyPanel))
  check("M6.1: the viewer offers 'Shown as' on a frame", await visible(page.getByTestId("viewer-positive")))
  await shot(page, 16, "a frame edited in NegPy")
  await page.keyboard.press("Escape")

  // "Open in NegPy": a folder of hard links plus a metadata preset.
  check(
    "M5: Open in NegPy prepares the roll",
    await clickUntil(page.getByTestId("open-in-negpy"), page.getByTestId("handoff-steps")),
  )
  const handoffText = (await page.getByTestId("handoff-steps").textContent()) || ""
  check("M5: the handoff names the export pattern", handoffText.includes("{{ roll }}_{{ frame|pad(3) }}_{{ film }}"))
  check(
    "M5: the handoff folder is named after the serial",
    handoffText.includes(serialText),
    handoffText.slice(0, 160),
  )
  check(
    "M5: the dialog does not overflow its width",
    await page.getByTestId("handoff-steps").evaluate((el) => {
      const dialog = el.closest('[role="dialog"]')
      return el.getBoundingClientRect().width <= dialog.getBoundingClientRect().width + 1
    }),
  )
  await shot(page, 17, "ready for NegPy")
  await page.getByRole("button", { name: "Done" }).click()

  // The development fields (M5): what the file said ends up in its own columns,
  // not appended to the roll's notes.
  await page.goto(`${BASE_URL}/films/${rollId}`, { waitUntil: "load" })
  const developedIn = (await page.getByTestId("roll-development").textContent().catch(() => "")) || ""
  check("M5: the roll shows how it was developed", /Rodinal/.test(developedIn), developedIn.trim() || "none")
  check(
    "M5: the roll editor has the development fields",
    await clickUntil(page.getByTestId("edit-roll"), page.getByTestId("development-fields")),
  )
  check(
    "M5: the developer field carries what the file said",
    (await page.locator("#edit-developer").inputValue()) === "Rodinal",
  )
  await page.keyboard.press("Escape")

  // M5: printing the negative. The scan stays the scan; the preview is derived.
  // On a *plain* scan: the NegPy upload above is an export, and an export is a
  // positive the archive refuses to print (M6.1) — checked right after.
  const rollImages = (await (await page.request.get(`${BASE_URL}/api/films/${rollId}`)).json()).images
  const plainScan = rollImages.find((image) => image.id !== negpyUpload.id && image.type === "scan")
  const renderModes = {}
  for (const wanted of ["raw", "positive"]) {
    const res = await page.request.get(
      `${BASE_URL}/api/images/${plainScan.id}/preview?width=200&render=${wanted}`,
    )
    renderModes[wanted] = { status: res.status(), header: res.headers()["x-preview-render"] }
  }
  check(
    "M5: a frame can be served raw or printed as a positive",
    renderModes.raw.header === "raw" && renderModes.positive.header === "positive",
    JSON.stringify(renderModes),
  )
  const exportPrinted = await page.request.get(
    `${BASE_URL}/api/images/${negpyUpload.id}/preview?width=200&render=positive`,
  )
  check(
    "M6.1: an export is shown as it is even when asked to print it",
    exportPrinted.headers()["x-preview-render"] === "raw",
    String(exportPrinted.headers()["x-preview-render"]),
  )

  await page.goto(`${BASE_URL}/films/${rollId}`, { waitUntil: "load" })
  await visible(page.getByTestId("frame-cell"))
  await page.getByTestId("frame-cell").first().click()
  check("M5: the viewer has a render toggle", await visible(page.getByTestId("viewer-render-toggle")))
  const srcBefore = await page.getByTestId("viewer-image").getAttribute("src")
  await page.getByTestId("viewer-render-toggle").click()
  await page.waitForTimeout(600)
  const srcAfter = await page.getByTestId("viewer-image").getAttribute("src")
  check(
    "M5: the toggle asks the backend for the other rendering",
    srcBefore !== srcAfter && /render=(raw|positive)/.test(srcAfter || ""),
    `${srcBefore} → ${srcAfter}`,
  )
  await page.keyboard.press("Escape")

  // Settings: the NegPy section, and writing the gear library NegPy reads.
  await page.goto(`${BASE_URL}/settings`, { waitUntil: "load" })
  check("M5: the settings page has a NegPy section", await visible(page.getByTestId("negpy-settings")))
  // M6.2/M6.3: the archive's own share, first thing on the page: the address, the
  // Mac steps with the share's own paths, live mode, and what is in the inbox.
  check("M6.3: the settings page shows the share", await visible(page.getByTestId("share-card")))
  const shareText = (await page.getByTestId("share-card").textContent()) || ""
  check("M6.3: the share card names the export folder", shareText.includes("/Volumes/negarchive/inbox"))
  check("M6.3: the share card names the scan folder", shareText.includes("/Volumes/negarchive/rolls"))
  check("M6.3: the share card gives the filename pattern", shareText.includes("{{ roll }}_{{ frame|pad(3) }}_{{ film }}"))
  check("M6.2: the inbox reports what is waiting", await visible(page.getByTestId("inbox-readout")))
  check("M6.3: live mode has a Set up button", await visible(page.getByTestId("share-setup")))
  await page.getByTestId("share-setup").click()
  await page.waitForTimeout(1500)
  check(
    "M6.3: one press sets live mode up on the served share",
    /Live mode is set up/.test((await page.getByTestId("live-readout").textContent()) || ""),
  )
  // The two address overrides live under This machine.
  check("M6.3: there is an address field for links", await visible(page.getByTestId("links-address")))
  check("M6.3: there is an address field for the share", await visible(page.getByTestId("share-address")))
  await page.getByTestId("share-address").fill("archive.local")
  await page.getByTestId("share-address").press("Enter")
  await page.waitForTimeout(800)
  await page.reload({ waitUntil: "load" })
  check(
    "M6.3: the share address override reaches the card",
    ((await page.getByTestId("share-card").textContent()) || "").includes("smb://archive.local/negarchive"),
  )
  await page.getByTestId("share-address").fill("")
  await page.getByTestId("share-address").press("Enter")
  await page.waitForTimeout(500)
  // The NAS mount is still there, but out of the way.
  check("M6.3: the NAS mount is under Advanced", await visible(page.getByTestId("advanced-nas")))
  check("M5: metadata ingest is on by default", await visible(page.getByTestId("negpy-ingest-toggle")))
  await page.getByTestId("negpy-sync-gear").click()
  await page.waitForTimeout(1500)
  const gearWritten = await page.evaluate(async () => {
    const res = await fetch("/api/negpy/status")
    const status = await res.json()
    return Boolean(status.gear_synced_at)
  })
  check("M5: writing the gear library records when it ran", gearWritten)
  check("M5: previews can be switched between raw and printed", await visible(page.getByTestId("preview-render")))
  check(
    "M5: the settings page reports NegPy's edits.db",
    await visible(page.getByTestId("negpy-edits-readout")),
  )
  const editsReadout = (await page.getByTestId("negpy-edits-readout").textContent()) || ""
  check(
    "M5: with no edits.db it says so rather than failing",
    /No NegPy edits\.db|edits\.db:/.test(editsReadout),
    editsReadout.trim(),
  )
  // From Node, not from the page: this request is *meant* to 404, and a 404 in the
  // page would be logged as a console error and fail the "no console errors" check.
  const editsMatch = await page.request.post(`${BASE_URL}/api/negpy/edits/match`, { data: {} })
  const editsBody = await editsMatch.json().catch(() => null)
  check(
    "M5: matching against a missing edits.db is a clean 404",
    editsMatch.status() === 404 && editsBody?.error?.code === "no_edits_db",
    `${editsMatch.status()} ${JSON.stringify(editsBody).slice(0, 120)}`,
  )

  const lookupOk = await page.evaluate(async (hash) => {
    const res = await fetch(`/api/negpy/lookup?hash=${hash}`)
    const payload = await res.json()
    return payload.count >= 1
  }, negpyUpload?.content_hash)
  check("M5: a frame can be found by its NegPy content hash", lookupOk)

  // ------------------------------------------------- clean up what we created
  // Also the only test of the delete dialog, and it keeps the archive tidy so a
  // screenshot run does not show this script's leftovers.
  await page.goto(BASE_URL, { waitUntil: "load" })
  await page.getByTestId("roll-search").first().fill(title)
  await page.waitForTimeout(FILTER_MS)
  check(
    "deleting a roll asks first",
    await clickUntil(page.getByLabel(`Delete ${title}`), page.getByRole("alertdialog")),
  )
  // M2: the dialog offers to leave the files on disk (R#9); left unticked, the
  // scans are deleted with the records, which is what this run wants.
  check("the delete dialog offers to keep the files", await visible(page.getByTestId("keep-files")))
  await page.getByRole("button", { name: "Delete", exact: true }).click()
  await page.waitForTimeout(1200)
  check("the roll is gone after confirming", (await page.getByTestId("roll-row").count()) === 0)

  // ---------------------------------------------------------------- 375px
  const mobile = await browser.newContext({ viewport: MOBILE, isMobile: true, hasTouch: true })
  const small = await mobile.newPage()
  watchConsole(small, consoleErrors)

  await small.goto(BASE_URL, { waitUntil: "load" })
  check(
    "no horizontal scrolling at 375px",
    await small.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1),
    await small.evaluate(() => `scrollWidth ${document.documentElement.scrollWidth}`),
  )
  check("the nav collapses to a menu button", await visible(small.getByLabel("Open navigation")))
  await shot(small, 4, "roll list at 375px")

  check(
    "the mobile nav opens in a sheet",
    await clickUntil(small.getByLabel("Open navigation"), small.getByRole("dialog")),
  )
  await small.keyboard.press("Escape")

  await openFullestRoll(small)
  check("the roll workspace works at 375px", await visible(small.getByTestId("frame-grid")))
  check(
    "no horizontal scrolling on the roll page at 375px",
    await small.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1),
  )
  await shot(small, 5, "roll workspace at 375px")

  for (const route of ["/images", "/gear", "/films", "/locations", "/scan", "/print/queue"]) {
    await small.goto(BASE_URL + route, { waitUntil: "load" })
    check(
      `${route} has no horizontal scrolling at 375px`,
      await small.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1),
    )
  }

  await browser.close()

  check("no console errors anywhere", consoleErrors.length === 0, consoleErrors.slice(0, 5).join(" | "))

  console.log(notes.join("\n"))
  console.log(
    `\n${failures.length === 0 ? "PASS" : "FAIL"}: ${notes.filter((n) => n.includes(" ok ")).length} checks ok, ${failures.length} failed`,
  )
  if (failures.length > 0) {
    console.log(failures.map((f) => ` - ${f}`).join("\n"))
    process.exit(1)
  }
}

main().catch((error) => {
  console.error(error)
  process.exit(1)
})
