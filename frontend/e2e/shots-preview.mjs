/**
 * The two preview screenshots in the README: the same frame printed and raw (M5).
 *
 *   BASE_URL=http://localhost:3011 ROLL_ID=8 node e2e/shots-preview.mjs ../screenshots
 *
 * Needs a roll of actual negatives; `scripts/seed_demo.py` makes positives, so
 * this is run against a roll seeded for the purpose.
 */
import { chromium } from "playwright"
import path from "node:path"

const BASE_URL = process.env.BASE_URL || "http://localhost:3010"
const OUT = process.argv[2] || "../screenshots"
const ROLL = process.env.ROLL_ID || "8"

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })

await page.goto(`${BASE_URL}/films/${ROLL}`, { waitUntil: "load" })
await page.getByTestId("frame-cell").first().waitFor()
await page.waitForFunction(() => Array.from(document.images).every((i) => i.complete))

// The frame as it is printed, with the line that says how much of the recipe
// this render could actually apply…
await page.getByTestId("frame-cell").first().click()
await page.getByTestId("frame-viewer").waitFor()
await page.waitForTimeout(900)
await page.screenshot({ path: path.join(OUT, "screenshot-18.png") })

// …and the same frame as the scanner handed it over, which is the file the
// archive actually stores.
await page.getByTestId("viewer-render-toggle").click()
await page.waitForTimeout(1200)
await page.screenshot({ path: path.join(OUT, "screenshot-19.png") })

await browser.close()
console.log(`wrote screenshot-18/19.png to ${OUT}`)
