// Visual capture of the Championship Standings (/leaderboard) and Driver Card
// (/driver/[wallet]) pages with NO backend. Mocks are scoped to the API host
// (:8000) so they don't intercept the Next page documents on :3000.
//   next dev up on :3000, then: node scripts/collector-screenshot.mjs
import { chromium } from "playwright";

const C = "0xb8ea78fcacef50d41375e44e6814ebba36bb33c4";
const W = "0x70997970c51812dc3a010c7d01b50e0d17dc79c8";
const API = "http://localhost:8000";

const TIERS = [
  { tier: "Common", rank: 0, cap: 1000, slots_filled: 214, slots_remaining: 786, racers: 0, points: 5 },
  { tier: "Uncommon", rank: 1, cap: 750, slots_filled: 88, slots_remaining: 662, racers: 31, points: 10 },
  { tier: "Rare", rank: 2, cap: 500, slots_filled: 145, slots_remaining: 355, racers: 12, points: 15 },
  { tier: "Super Rare", rank: 3, cap: 250, slots_filled: 40, slots_remaining: 210, racers: 3, points: 25 },
  { tier: "Mythic", rank: 4, cap: 50, slots_filled: 7, slots_remaining: 43, racers: 2, points: 50 },
];

const standings = {
  contract_address: C,
  tiers: TIERS,
  collectors: [
    { wallet_address: W, tiers_won: ["Mythic", "Rare", "Rare", "Common"], championship_points: 85, badges_won: 4, rank: 1, latest_at: "2026-07-16T10:00:00Z" },
    { wallet_address: "0xabcabcabcabcabcabcabcabcabcabcabcabcabca", tiers_won: ["Super Rare", "Uncommon"], championship_points: 35, badges_won: 2, rank: 2, latest_at: "2026-07-15T10:00:00Z" },
    { wallet_address: "0x51f0a3d0000000000000000000000000000051f0", tiers_won: ["Rare"], championship_points: 15, badges_won: 1, rank: 3, latest_at: "2026-07-14T10:00:00Z" },
  ],
};

const driver = {
  contract_address: C,
  wallet_address: W,
  championship_points: 85,
  badges_won: 4,
  tiers: [
    { tier: "Common", rank: 0, state: "won", won_count: 1, slot_numbers: [212], held_count: 9, count_required: 1, progress_pct: 100, needed: 0, points: 5 },
    { tier: "Uncommon", rank: 1, state: "racing", won_count: 0, slot_numbers: [], held_count: 5, count_required: 3, progress_pct: 100, needed: 0, points: 10 },
    { tier: "Rare", rank: 2, state: "won", won_count: 2, slot_numbers: [44, 77], held_count: 4, count_required: 2, progress_pct: 100, needed: 0, points: 15 },
    { tier: "Super Rare", rank: 3, state: "locked", won_count: 0, slot_numbers: [], held_count: 1, count_required: 2, progress_pct: 50, needed: 1, points: 25 },
    { tier: "Mythic", rank: 4, state: "won", won_count: 1, slot_numbers: [3], held_count: 3, count_required: 3, progress_pct: 100, needed: 0, points: 50 },
  ],
};

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1400 } });
const errors = [];
page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
page.on("pageerror", (e) => errors.push(String(e)));

await page.route(`${API}/standings/**`, (r) =>
  r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(standings) }),
);
await page.route(`${API}/driver/**`, (r) =>
  r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(driver) }),
);

// --- Leaderboard: standings tab ---
await page.goto("http://localhost:3000/leaderboard", { waitUntil: "networkidle", timeout: 90000 });
await page.fill(".rc-input", C);
await page.click(".rc-load");
try {
  await page.waitForSelector(".cb-board", { timeout: 20000 });
} catch {
  console.log("cb-board not found; alert text:", await page.locator(".rc-alert").allTextContents().catch(() => []));
}
await page.waitForTimeout(500);
await page.screenshot({ path: "scripts/collector-standings.png", fullPage: true });
console.log("captured: collector-standings.png");

// --- Leaderboard: tiers tab ---
await page.click(".cb-tab:has-text('Tiers')").catch(() => {});
await page.waitForSelector(".cb-tiergrid", { timeout: 15000 }).catch(() => {});
await page.waitForTimeout(400);
await page.screenshot({ path: "scripts/collector-tiers.png", fullPage: true });
console.log("captured: collector-tiers.png");

// --- Driver card ---
await page.goto(`http://localhost:3000/driver/${W}?c=${C}`, { waitUntil: "networkidle", timeout: 90000 });
await page.waitForSelector(".dc-cabinet", { timeout: 20000 }).catch(() => console.log("dc-cabinet not found"));
await page.waitForTimeout(500);
await page.screenshot({ path: "scripts/collector-driver.png", fullPage: true });
console.log("captured: collector-driver.png");

console.log("console errors:", errors.length ? errors : "none");
await browser.close();
