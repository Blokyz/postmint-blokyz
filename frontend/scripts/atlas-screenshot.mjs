import { chromium } from "playwright";

const CONTRACT = "0xB8Ea78fcaCEf50d41375E44E6814ebbA36Bb33c4";

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 1100 } });

const errors = [];
page.on("console", (msg) => {
  if (msg.type() === "error") errors.push(msg.text());
});
page.on("pageerror", (err) => errors.push(String(err)));

await page.goto("http://localhost:3000/atlas", { waitUntil: "networkidle" });

await page.fill('input[placeholder^="0x"]', CONTRACT);
await page.click('button:has-text("Generate atlas")');

await page.waitForSelector(".atlas-grid", { timeout: 30000 });
await page.waitForTimeout(500);
await page.screenshot({ path: "scripts/atlas-1-initial.png", fullPage: true });

// Read Common tier's fit score before tuning.
const commonCard = page.locator(".atlas-tier", { has: page.locator("h2", { hasText: /^Common$/ }) });
const before = await commonCard.locator(".atlas-fit-value").textContent();
console.log("Common fit before:", before);

// Move the Common cap slider (first slider in the card) to its max.
const capSlider = commonCard.locator("input.atlas-slider").first();
const max = await capSlider.getAttribute("max");
await capSlider.fill(max);

await page.click('button:has-text("Regenerate")');
await page.waitForFunction(
  () => !document.querySelector(".atlas-regenerate")?.textContent?.includes("Regenerating"),
  { timeout: 30000 },
);
await page.waitForTimeout(500);
await page.screenshot({ path: "scripts/atlas-2-regenerated.png", fullPage: true });

const after = await commonCard.locator(".atlas-fit-value").textContent();
console.log("Common fit after (cap set to", max, "):", after);

console.log("Console errors:", errors);

await browser.close();
