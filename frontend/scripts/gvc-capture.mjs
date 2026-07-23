import { chromium } from "playwright";
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
const targets = [
  ["https://www.goodvibesclub.io/", "gvc-home.png"],
  ["https://www.goodvibesclub.io/badges/leaderboard", "gvc-leaderboard.png"],
];
for (const [url, file] of targets) {
  try {
    await page.goto(url, { waitUntil: "networkidle", timeout: 45000 });
    await page.waitForTimeout(2500);
    await page.screenshot({ path: `scripts/${file}` });
    console.log("captured:", file);
  } catch (e) {
    console.log("FAILED", url, String(e).split("\n")[0]);
  }
}
await browser.close();
