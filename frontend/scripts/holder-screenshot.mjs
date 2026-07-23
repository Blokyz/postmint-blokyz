// Visual capture of the restructured holder app (Phase 3): the Collections
// directory (/), a collection landing (/c/[slug]), standings, and a driver card —
// all with NO backend. API mocks are scoped to :8000 so they don't intercept the
// Next page documents on :3000.
//   next dev on :3000, then: node scripts/holder-screenshot.mjs
import { chromium } from "playwright";

const SLUG = "good-vibes-club";
const C = "0xb8ea78fcacef50d41375e44e6814ebba36bb33c4";
const W = "0x70997970c51812dc3a010c7d01b50e0d17dc79c8";
const API = "http://localhost:8000";

const collection = {
  slug: SLUG,
  contract_address: C,
  display_name: "Good Vibes Club",
  chain: "eth",
  image_url: null,
  published: true,
};

const directory = [
  { ...collection, tier_count: 5, total_cap: 2550, total_filled: 312, racers: 43, status: "live" },
  {
    slug: "cool-cats",
    contract_address: "0x1a92f7381b9f03921564a437210bb9396471050c",
    display_name: "Cool Cats",
    chain: "eth",
    image_url: null,
    published: true,
    tier_count: 4,
    total_cap: 1200,
    total_filled: 1200,
    racers: 0,
    status: "full",
  },
  {
    slug: "azuki",
    contract_address: "0xed5af388653567af2f388e6224dc7c4b3241c544",
    display_name: "Azuki",
    chain: "eth",
    image_url: null,
    published: true,
    tier_count: 5,
    total_cap: 2550,
    total_filled: 2400,
    racers: 61,
    status: "ending_soon",
  },
];

const standings = {
  contract_address: C,
  tiers: [
    { tier: "Common", rank: 0, cap: 1000, slots_filled: 214, slots_remaining: 786, racers: 0, points: 5 },
    { tier: "Uncommon", rank: 1, cap: 750, slots_filled: 88, slots_remaining: 662, racers: 31, points: 10 },
    { tier: "Rare", rank: 2, cap: 500, slots_filled: 145, slots_remaining: 355, racers: 12, points: 15 },
    { tier: "Super Rare", rank: 3, cap: 250, slots_filled: 40, slots_remaining: 210, racers: 3, points: 25 },
    { tier: "Mythic", rank: 4, cap: 50, slots_filled: 7, slots_remaining: 43, racers: 2, points: 50 },
  ],
  collectors: [
    { wallet_address: W, tiers_won: ["Mythic", "Super Rare", "Rare", "Rare", "Uncommon", "Common"], championship_points: 105, badges_won: 6, rank: 1, latest_at: "2026-07-16T10:00:00Z" },
    { wallet_address: "0xd8da6bf26964af9d7eed9e03e53415d37aa96045", tiers_won: ["Mythic", "Rare", "Uncommon", "Common"], championship_points: 80, badges_won: 4, rank: 2, latest_at: "2026-07-16T09:00:00Z" },
    { wallet_address: "0xabcabcabcabcabcabcabcabcabcabcabcabcabca", tiers_won: ["Super Rare", "Rare", "Uncommon", "Common"], championship_points: 55, badges_won: 4, rank: 3, latest_at: "2026-07-15T10:00:00Z" },
    { wallet_address: "0x1db3439a222c519ab44bb1144fc28167b4fa6ee6", tiers_won: ["Super Rare", "Uncommon", "Common"], championship_points: 40, badges_won: 3, rank: 4, latest_at: "2026-07-15T08:00:00Z" },
    { wallet_address: "0x220866b1a2219f40e72f5c628b65d54268ca3a9d", tiers_won: ["Rare", "Uncommon", "Common"], championship_points: 30, badges_won: 3, rank: 5, latest_at: "2026-07-14T22:00:00Z" },
    { wallet_address: "0x8ba1f109551bd432803012645ac136ddd64dba72", tiers_won: ["Rare", "Common"], championship_points: 20, badges_won: 2, rank: 6, latest_at: "2026-07-14T18:00:00Z" },
    { wallet_address: "0x7d1afa7b718fb893db30a3abc0cfc608aacfebb0", tiers_won: ["Uncommon", "Common"], championship_points: 15, badges_won: 2, rank: 7, latest_at: "2026-07-14T12:00:00Z" },
    { wallet_address: "0x00000000219ab540356cbb839cbe05303d7705fa", tiers_won: ["Uncommon", "Common"], championship_points: 15, badges_won: 2, rank: 8, latest_at: "2026-07-14T10:00:00Z" },
    { wallet_address: "0x3fc91a3afd70395cd496c647d5a6cc9d4b2b7fad", tiers_won: ["Common", "Common"], championship_points: 10, badges_won: 2, rank: 9, latest_at: "2026-07-13T20:00:00Z" },
    { wallet_address: "0x28c6c06298d514db089934071355e5743bf21d60", tiers_won: ["Common"], championship_points: 5, badges_won: 1, rank: 10, latest_at: "2026-07-13T14:00:00Z" },
    { wallet_address: "0xbe0eb53f46cd790cd13851d5eff43d12404d33e8", tiers_won: ["Common"], championship_points: 5, badges_won: 1, rank: 11, latest_at: "2026-07-13T09:00:00Z" },
    { wallet_address: "0xf977814e90da44bfa03b6295a0616a897441acec", tiers_won: ["Common"], championship_points: 5, badges_won: 1, rank: 12, latest_at: "2026-07-12T18:00:00Z" },
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
const page = await browser.newPage({ viewport: { width: 1440, height: 1500 } });
const errors = [];
page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
page.on("pageerror", (e) => errors.push(String(e)));

const json = (body) => (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
await page.route(`${API}/collections`, json(directory)); // exact: directory list
await page.route(`${API}/collections/**`, json(collection)); // resolve slug
await page.route(`${API}/standings/**`, json(standings));
await page.route(`${API}/driver/**`, json(driver));

async function shot(path, waitSel, file) {
  await page.goto(`http://localhost:3000${path}`, { waitUntil: "networkidle", timeout: 90000 });
  if (waitSel) await page.waitForSelector(waitSel, { timeout: 20000 }).catch(() => console.log(`  (${waitSel} not found on ${path})`));
  await page.waitForTimeout(700);
  await page.screenshot({ path: `scripts/${file}`, fullPage: true });
  console.log(`captured: ${file}`);
}

await shot("/", ".dir-grid", "holder-directory.png");
await shot(`/c/${SLUG}`, ".land-hero", "holder-landing.png");
await shot(`/c/${SLUG}/standings`, ".lb-board", "holder-standings.png");
await shot(`/c/${SLUG}/driver/${W}`, ".dc-cabinet", "holder-driver.png");

console.log("console errors:", errors.length ? errors : "none");
await browser.close();
