// Visual capture of the /race timing-tower page with NO backend or chain.
// Injects a minimal EIP-6963 wallet (chain-aware, no RPC forwarding needed since
// the page does no on-chain reads on load) so wagmi can connect, then fulfills
// /eligibility, /claim/status/* and /leaderboard/* from fixtures covering every
// lane state (standby / on-track / ready / finished / not-eligible).
//   next dev up on :3000, then: node scripts/race-screenshot.mjs
import { chromium } from "playwright";

const CONTRACT = "0xb8ea78fcacef50d41375e44e6814ebba36bb33c4";
const ACCOUNT = "0x70997970c51812dc3a010c7d01b50e0d17dc79c8";
const ME = ACCOUNT.toLowerCase();
const CHAIN_HEX = "0x14a34"; // 84532 Base Sepolia

// Per-tier fixtures. `elig` drives the meter/chips; `ws` drives the clock/state;
// `lb` drives the standings.
const TIERS = [
  { tier: "Common", archetype: "count_of_pool", req: 1, held: 4, tokens: [11, 42, 108, 777], status: "not_started", secs: null, winSecs: 0, cap: 1000, filled: 214, racers: 0, winners: [] },
  { tier: "Uncommon", archetype: "count_of_pool", req: 3, held: 5, tokens: [12, 91, 305, 512, 880], status: "racing", secs: 40320, winSecs: 86400, cap: 750, filled: 88, racers: 31, winners: [] },
  { tier: "Rare", archetype: "count_of_pool", req: 2, held: 2, tokens: [7, 240], status: "ready", secs: 0, winSecs: 259200, cap: 500, filled: 145, racers: 12, winners: [] },
  { tier: "Super Rare", archetype: "count_of_pool", req: 2, held: 3, tokens: [4, 66, 512], status: "won", secs: null, winSecs: 604800, cap: 250, filled: 40, racers: 3, winners: [{ w: ME, slot: 41 }] },
  { tier: "Mythic", archetype: "apex_combo", req: 3, held: 1, tokens: [4], status: "not_started", secs: null, winSecs: 1209600, cap: 50, filled: 7, racers: 2, winners: [{ w: "0xabcabcabcabcabcabcabcabcabcabcabcabcabca", slot: 1 }] },
];

function eligibility() {
  return {
    contract_address: CONTRACT,
    wallet_address: ME,
    tiers: TIERS.map((t) => ({
      tier: t.tier,
      archetype: t.archetype,
      count_required: t.req,
      held_count: t.held,
      qualifying_token_ids: t.tokens,
      qualifies: t.held >= t.req,
      progress_pct: Math.min(100, (t.held / t.req) * 100),
      needed: Math.max(0, t.req - t.held),
    })),
  };
}

function statusFor(t) {
  return {
    tier: t.tier,
    window_seconds: t.winSecs,
    qualifies: t.held >= t.req,
    held_count: t.held,
    count_required: t.req,
    progress_pct: Math.min(100, (t.held / t.req) * 100),
    qualifying_token_ids: t.tokens,
    window_started: t.status === "not_started" ? null : "2026-07-16T09:00:00+00:00",
    status: t.status,
    seconds_remaining: t.secs,
  };
}

function leaderboardFor(t) {
  return {
    contract_address: CONTRACT,
    tier: t.tier,
    cap: t.cap,
    window_seconds: t.winSecs,
    slots_filled: t.filled,
    slots_remaining: Math.max(0, t.cap - t.filled),
    winners: t.winners.map((x) => ({
      wallet_address: x.w,
      slot_number: x.slot,
      tokens: [4, 66],
      tx_hash: "0x" + "ab".repeat(32),
      won_at: "2026-07-16T10:00:00+00:00",
    })),
    racers: [],
  };
}

const byTier = Object.fromEntries(TIERS.map((t) => [t.tier, t]));

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1600 } });
const errors = [];
page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
page.on("pageerror", (e) => errors.push(String(e)));

await page.addInitScript(
  ({ account, chainHex }) => {
    const listeners = {};
    const provider = {
      isRabby: true,
      request: async ({ method }) => {
        switch (method) {
          case "eth_requestAccounts":
          case "eth_accounts":
            return [account];
          case "eth_chainId":
          case "net_version":
            return method === "net_version" ? String(parseInt(chainHex, 16)) : chainHex;
          case "wallet_switchEthereumChain":
          case "wallet_addEthereumChain":
            return null;
          case "wallet_requestPermissions":
          case "wallet_getPermissions":
            return [{ parentCapability: "eth_accounts" }];
          default:
            return null;
        }
      },
      on: (ev, fn) => ((listeners[ev] ??= []).push(fn), provider),
      removeListener: (ev, fn) => ((listeners[ev] = (listeners[ev] ?? []).filter((f) => f !== fn)), provider),
    };
    const detail = Object.freeze({
      info: Object.freeze({
        uuid: "d3adb33f-0000-4000-8000-000000000001",
        name: "Rabby Wallet",
        icon: "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciLz4=",
        rdns: "io.rabby",
      }),
      provider,
    });
    const announce = () => window.dispatchEvent(new CustomEvent("eip6963:announceProvider", { detail }));
    window.addEventListener("eip6963:requestProvider", announce);
    announce();
  },
  { account: ACCOUNT, chainHex: CHAIN_HEX },
);

// Mock the three GET endpoints.
await page.route("**/eligibility/**", (r) =>
  r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(eligibility()) }),
);
await page.route("**/claim/status/**", (r) => {
  const parts = new URL(r.request().url()).pathname.split("/");
  const tier = decodeURIComponent(parts[parts.length - 2]);
  r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(statusFor(byTier[tier])) });
});
await page.route("**/leaderboard/**", (r) => {
  const parts = new URL(r.request().url()).pathname.split("/");
  const tier = decodeURIComponent(parts[parts.length - 1]);
  r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(leaderboardFor(byTier[tier])) });
});

await page.goto("http://localhost:3000/race", { waitUntil: "networkidle" });

// Connect via the RainbowKit modal if not auto-connected.
const connectBtn = page.locator('button:has-text("Connect Wallet")');
if (await connectBtn.count()) {
  await connectBtn.first().click();
  await page.waitForSelector('[data-testid="rk-wallet-option-io.rabby"]', { timeout: 15000 });
  await page.click('[data-testid="rk-wallet-option-io.rabby"]');
  await page.waitForSelector(".rc-driver.is-live", { timeout: 15000 });
}

await page.fill(".rc-input", CONTRACT);
await page.click(".rc-load");
await page.waitForSelector(".rc-lane", { timeout: 15000 });
await page.waitForTimeout(1200); // let the staggered lane reveal + countdown settle

await page.screenshot({ path: "scripts/race-grid.png", fullPage: true });
console.log("captured: race-grid.png");
console.log("console errors:", errors.length ? errors : "none");
await browser.close();
