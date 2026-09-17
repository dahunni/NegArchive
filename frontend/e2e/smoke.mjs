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

  // filters
  await page.getByTestId("roll-search").fill("harbour")
  await page.waitForTimeout(150)
  check(
    "the search filter narrows the list",
    (await page.getByTestId("roll-row").count()) < rollsBefore,
  )
  await page.getByTestId("roll-search").fill("")

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
  check(
    "the uploaded frames are in the grid",
    (await page.getByTestId("frame-cell").count()) === 2,
    `${await page.getByTestId("frame-cell").count()} cells`,
  )

  // gear was remembered for next time
  const remembered = await page.evaluate(() => window.localStorage.getItem("negarchive.lastGear"))
  check("the wizard remembers the last gear", (remembered || "").includes("Nikon F5"), remembered ?? "null")

  // ---------------------------------------------------------------- inline edit
  const firstNumber = page.getByTestId("frame-number-input").first()
  await firstNumber.fill("17")
  await firstNumber.press("Enter")
  await page.waitForTimeout(700)
  await page.reload({ waitUntil: "load" })
  check(
    "an inline frame number survives a reload",
    (await page.getByTestId("frame-number-input").first().inputValue()) === "17",
  )

  const firstNote = page.getByTestId("frame-notes-input").first()
  await firstNote.fill("e2e note")
  await firstNote.press("Enter")
  await page.waitForTimeout(700)
  await page.reload({ waitUntil: "load" })
  check(
    "an inline note survives a reload",
    (await page.getByTestId("frame-notes-input").first().inputValue()) === "e2e note",
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
  await page.waitForTimeout(300)
  check(
    "deleting a roll asks first",
    await clickUntil(page.getByLabel(`Delete ${title}`), page.getByRole("alertdialog")),
  )
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
