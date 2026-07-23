// End-to-end browser test of the on-chain lock flow (LockPanel) against a
// local anvil node. Injects a minimal EIP-6963/EIP-1193 wallet ("Rabby") whose
// requests are forwarded straight to anvil — its dev accounts are unlocked, so
// eth_sendTransaction needs no signing UI. Run with:
//   anvil --chain-id 84532  (registry deployed, backend API up, next dev up)
//   node scripts/lock-e2e.mjs
import { chromium } from "playwright";

const CONTRACT = "0xB8Ea78fcaCEf50d41375E44E6814ebbA36Bb33c4";
const ACCOUNT = "0x70997970c51812dc3a010c7d01b50e0d17dc79c8"; // anvil #1
const RPC = "http://localhost:8545";

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 1200 } });

const errors = [];
page.on("console", (msg) => {
  if (msg.type() === "error") errors.push(msg.text());
});
page.on("pageerror", (err) => errors.push(String(err)));

// ── Inject the wallet shim before any app code runs ───────────────────────
await page.addInitScript(
  ({ account, rpc }) => {
    let id = 0;
    async function forward(method, params) {
      const res = await fetch(rpc, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ jsonrpc: "2.0", id: ++id, method, params: params ?? [] }),
      });
      const body = await res.json();
      if (body.error) {
        const e = new Error(body.error.message);
        e.code = body.error.code;
        e.data = body.error.data;
        throw e;
      }
      return body.result;
    }

    const listeners = {};
    const provider = {
      isRabby: true,
      request: async ({ method, params }) => {
        switch (method) {
          case "eth_requestAccounts":
          case "eth_accounts":
            return [account];
          case "wallet_switchEthereumChain":
          case "wallet_addEthereumChain":
            return null;
          case "wallet_requestPermissions":
            return [{ parentCapability: "eth_accounts" }];
          case "wallet_getPermissions":
            return [{ parentCapability: "eth_accounts" }];
          default:
            return forward(method, params);
        }
      },
      on: (ev, fn) => {
        (listeners[ev] ??= []).push(fn);
        return provider;
      },
      removeListener: (ev, fn) => {
        listeners[ev] = (listeners[ev] ?? []).filter((f) => f !== fn);
        return provider;
      },
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
    const announce = () =>
      window.dispatchEvent(new CustomEvent("eip6963:announceProvider", { detail }));
    window.addEventListener("eip6963:requestProvider", announce);
    announce();
  },
  { account: ACCOUNT, rpc: RPC },
);

// ── Load the atlas page and generate ──────────────────────────────────────
await page.goto("http://localhost:3000/atlas", { waitUntil: "networkidle" });
await page.fill('input[placeholder^="0x"]', CONTRACT);
await page.click('button:has-text("Generate atlas")');
await page.waitForSelector(".lock-panel", { timeout: 60000 });
await page.screenshot({ path: "scripts/lock-1-panel.png", fullPage: true });

// Lock button should be disabled until a wallet connects.
const lockBtn = page.locator(".lock-btn");
console.log("lock disabled before connect:", await lockBtn.isDisabled());

// ── Connect via RainbowKit (skip if wagmi already picked up the shim) ─────
const connectBtn = page.locator('button:has-text("Connect Wallet")');
if (await connectBtn.count()) {
  await connectBtn.first().click();
  await page.waitForSelector('[data-testid="rk-wallet-option-io.rabby"]', { timeout: 15000 });
  await page.click('[data-testid="rk-wallet-option-io.rabby"]');
  await page.waitForSelector('button:has-text("0x")', { timeout: 15000 });
  console.log("wallet connected via RainbowKit modal");
} else {
  console.log("wallet already connected (shim auto-connect — eth_accounts returns the account unconditionally)");
}
await page.screenshot({ path: "scripts/lock-2-connected.png", fullPage: true });

// ── Lock on-chain ─────────────────────────────────────────────────────────
await lockBtn.scrollIntoViewIfNeeded();
console.log("lock disabled after connect:", await lockBtn.isDisabled());
await lockBtn.click();

// Attestation tuple should render, then the locked badge once the tx mines.
await page.waitForSelector(".lock-state.is-locked", { timeout: 60000 });
await page.screenshot({ path: "scripts/lock-3-locked.png", fullPage: true });

const tuple = await page.locator(".lock-tuple").allTextContents().catch(() => []);
console.log("locked badge shown; tuple:", tuple);

// Surface any console errors (filter benign dev noise if needed).
console.log("Console errors:", errors);

await browser.close();
