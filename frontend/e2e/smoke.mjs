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
  await page.getByTestId("roll-search").fill("harbour")
  await page.waitForTimeout(FILTER_MS)
  const narrowed = await page.getByTestId("roll-row").count()
  check("the search filter narrows the list", narrowed < rollsBefore, `${narrowed} of ${rollsBefore}`)
  check("the search is server-side", narrowed > 0, "seeded archive has 'harbour' rolls")
  await page.getByTestId("roll-search").fill("")
  await page.waitForTimeout(FILTER_MS)

  // /films renders the same page
  await page.goto(`${BASE_URL}/films`, { waitUntil: "load" })
  check("/films still works", await visible(page.getByTestId("roll-list")))

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
  await page.locator("#wizard-building").fill("Archive A")
  await page.locator("#wizard-serial").fill("NEG-E2E-001")
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
  await page.getByRole("checkbox").first().click()
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

  // ------------------------------------------------- clean up what we created
  // Also the only test of the delete dialog, and it keeps the archive tidy so a
  // screenshot run does not show this script's leftovers.
  await page.goto(BASE_URL, { waitUntil: "load" })
  await page.getByTestId("roll-search").fill(title)
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

  for (const route of ["/images", "/gear", "/films"]) {
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
