import { chromium } from "playwright";

// Good Vibes Club — a completed ingestion already in the DB (richly-trait collection).
const CONTRACT = "0xb8ea78fcacef50d41375e44e6814ebba36bb33c4";

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 1400 } });
const errors = [];
page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
page.on("pageerror", (e) => errors.push(String(e)));

await page.goto("http://localhost:3000/approve", { waitUntil: "networkidle" });
await page.fill(".al-loadbar input", CONTRACT);
await page.click(".al-loadbar button");
await page.waitForSelector(".al-trait-list", { timeout: 30000 });
await page.waitForTimeout(600);

const total = await page.locator(".al-stat.is-accent .al-stat-value").textContent();
console.log("Total traits shown:", total);

await page.screenshot({ path: "scripts/approve-loaded.png", fullPage: true });

// Pin a couple of top traits + apply a search filter for the second shot.
const pins = page.locator(".al-pin");
await pins.nth(0).click();
await pins.nth(2).click();
await page.fill(".al-search", "background");
await page.waitForTimeout(400);
await page.screenshot({ path: "scripts/approve-filtered.png", fullPage: true });

console.log("console errors:", errors.length ? errors : "none");
await browser.close();
