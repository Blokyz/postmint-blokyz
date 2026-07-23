// Mocks /atlas/generate + /atlas/lock-attestation via route interception so the
// lock panel can be verified with NO backend. Captures the no-wallet render
// (Lock button disabled + connect prompt) and the dirty-guard note after a
// slider move. Wallet-connected path (button enabled, tuple shown) still needs a
// manual check with a real extension.
import { chromium } from "playwright";

const CONTRACT = "0xb8ea78fcacef50d41375e44e6814ebba36bb33c4";

const ATLAS = {
  atlas_manifest_id: "11111111-2222-3333-4444-555555555555",
  ranking_manifest_id: "66666666-7777-8888-9999-000000000000",
  collection: { contract_address: CONTRACT, chain: "base", total_supply: 6968, eligible_supply: 6968 },
  generated_at: "2026-06-30T00:00:00Z",
  tier_structure: {
    Common: { cap: 1000, holding_window_hours: 0 },
    Uncommon: { cap: 750, holding_window_hours: 24 },
    Rare: { cap: 500, holding_window_hours: 72 },
    "Super Rare": { cap: 250, holding_window_hours: 168 },
    Mythic: { cap: 50, holding_window_hours: 336 },
  },
  ladders: [],
  approval: null,
  tiers: [
    { tier: "Mythic", set_rule: { archetype: "apex_combo", pool: [{ trait_category: "Aura", trait_value: "Gold" }], count_required: 1 }, pool: [{ trait_category: "Aura", trait_value: "Gold" }], feasibility: { pool_qualifying_nfts: 12, estimated_qualifiers: 36, max_sets_formable: 12, race_intensity: 3.0, fit_score: 3.0 }, low_feasibility: false },
    { tier: "Super Rare", set_rule: { archetype: "one_of_each", trait_values: [{ trait_category: "Hat", trait_value: "Crown" }, { trait_category: "Eyes", trait_value: "Laser" }] }, pool: [{ trait_category: "Hat", trait_value: "Crown" }], feasibility: { pool_qualifying_nfts: 66, estimated_qualifiers: 7, max_sets_formable: 33, race_intensity: 2.8, fit_score: 2.8 }, low_feasibility: false },
    { tier: "Rare", set_rule: { archetype: "count_of_pool", pool: [{ trait_category: "Bg", trait_value: "Blue" }], count_required: 2 }, pool: [{ trait_category: "Bg", trait_value: "Blue" }], feasibility: { pool_qualifying_nfts: 122, estimated_qualifiers: 145, max_sets_formable: 61, race_intensity: 0.29, fit_score: 0.29 }, low_feasibility: true },
    { tier: "Uncommon", set_rule: { archetype: "count_of_pool", pool: [{ trait_category: "Bg", trait_value: "Red" }], count_required: 2 }, pool: [{ trait_category: "Bg", trait_value: "Red" }], feasibility: { pool_qualifying_nfts: 162, estimated_qualifiers: 272, max_sets_formable: 81, race_intensity: 0.36, fit_score: 0.36 }, low_feasibility: true },
    { tier: "Common", set_rule: { archetype: "count_of_pool", pool: [{ trait_category: "Body", trait_value: "Tan" }], count_required: 3 }, pool: [{ trait_category: "Body", trait_value: "Tan" }], feasibility: { pool_qualifying_nfts: 2000, estimated_qualifiers: 3000, max_sets_formable: 666, race_intensity: 3.0, fit_score: 3.0 }, low_feasibility: false },
  ],
};

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 1300 } });

const errors = [];
page.on("console", (msg) => { if (msg.type() === "error") errors.push(msg.text()); });
page.on("pageerror", (err) => errors.push(String(err)));

await page.route("**/atlas/generate", (route) =>
  route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(ATLAS) }),
);
await page.route("**/atlas/lock-attestation", (route) =>
  route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      contract_address: CONTRACT,
      ranking_hash: "0x" + "ab".repeat(32),
      atlas_hash: "0x" + "cd".repeat(32),
      signature: "0x" + "ef".repeat(65),
      backend_signer: "0x1111111111111111111111111111111111111111",
      registry_address: "0x2222222222222222222222222222222222222222",
      chain_id: 84532,
    }),
  }),
);

await page.goto("http://localhost:3000/atlas", { waitUntil: "networkidle" });
await page.fill('input[placeholder^="0x"]', CONTRACT);
await page.click('button:has-text("Generate atlas")');
await page.waitForSelector(".lock-panel", { timeout: 30000 });
await page.waitForTimeout(400);

const btnText = await page.locator(".lock-btn").textContent();
const btnDisabled = await page.locator(".lock-btn").isDisabled();
const connectNote = await page.locator(".lock-note").first().textContent();
console.log("Lock button:", JSON.stringify(btnText), "disabled:", btnDisabled);
console.log("Note:", JSON.stringify(connectNote));

await page.locator(".lock-panel").scrollIntoViewIfNeeded();
await page.screenshot({ path: "scripts/lock-1-panel.png", fullPage: true });

// Move a slider to make the atlas "dirty" and confirm the guard note appears.
const capSlider = page.locator(".atlas-tier input.atlas-slider").first();
const max = await capSlider.getAttribute("max");
await capSlider.fill(max);
await page.waitForTimeout(200);
const dirtyNote = (await page.locator(".lock-note").allTextContents()).find((t) => t.includes("Unsaved"));
console.log("Dirty guard note present:", Boolean(dirtyNote));

console.log("Console errors:", errors);
await browser.close();
