/**
 * The two M5 screenshots in the README (roadmap M5).
 *
 *   BASE_URL=http://localhost:3011 node e2e/shots-m5.mjs ../screenshots
 *
 * Kept next to the smoke test because it drives the same UI, and separate from it
 * because these two shots need a roll that has actually been through NegPy.
 */
import { chromium } from "playwright"
import path from "node:path"

const BASE_URL = process.env.BASE_URL || "http://localhost:3010"
const OUT = process.argv[2] || "../screenshots"
const ROLL = process.env.ROLL_ID || "2"

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })

await page.goto(`${BASE_URL}/films/${ROLL}`, { waitUntil: "load" })
await page.getByTestId("frame-cell").first().waitFor()
await page.waitForFunction(() => Array.from(document.images).every((i) => i.complete))

// The frame that came back from NegPy: its own metadata, and the recipe summary.
const cells = page.getByTestId("frame-cell")
const count = await cells.count()
for (let index = 0; index < count; index++) {
  await cells.nth(index).click()
  await page.getByTestId("frame-viewer").waitFor()
  if (await page.getByTestId("viewer-negpy").count()) break
  await page.keyboard.press("Escape")
}
await page.waitForTimeout(800)
await page.screenshot({ path: path.join(OUT, "screenshot-16.png") })
await page.keyboard.press("Escape")

// "Open in NegPy": the prepared folder and the preset.
await page.getByTestId("open-in-negpy").click()
await page.getByTestId("handoff-steps").waitFor()
await page.waitForTimeout(600)
await page.screenshot({ path: path.join(OUT, "screenshot-17.png") })

await browser.close()
console.log(`wrote screenshot-16.png and screenshot-17.png to ${OUT}`)
