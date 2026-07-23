// Hands-on review driver. Hits the REAL backend on :8000 (no route mocks) with a
// wallet shim reporting a real Good Vibes holder (255 tokens → qualifies), walks
// every holder + operator route, screenshots full page, and dumps console errors
// + a trimmed visible-text snapshot so we can judge what a user actually sees.
import { chromium } from "playwright";
import fs from "fs";

const OUT = "scripts/review";
fs.mkdirSync(OUT, { recursive: true });

const WHALE = "0xf41b389e0c1950dc0b16c9498eae77131cc08a56"; // 255 GVC tokens
const SLUG = "good-vibes-club";
const CONTRACT = "0xb8ea78fcacef50d41375e44e6814ebba36bb33c4";
const CHAIN_HEX = "0x14a34";

const routes = [
  { name: "01-holder-directory", url: "/", persona: "holder" },
  { name: "02-holder-landing", url: `/c/${SLUG}`, persona: "holder" },
  { name: "03-holder-standings", url: `/c/${SLUG}/standings`, persona: "holder" },
  { name: "04-holder-race", url: `/c/${SLUG}/race`, persona: "holder", wait: 3500 },
  { name: "05-holder-driver", url: `/c/${SLUG}/driver/${WHALE}`, persona: "holder", wait: 2500 },
  { name: "06-operator-studio", url: "/studio", persona: "operator" },
  { name: "07-operator-ingest", url: "/ingest", persona: "operator" },
  { name: "08-operator-approve", url: "/approve", persona: "operator" },
  { name: "09-operator-atlas", url: "/atlas", persona: "operator" },
];

const shim = ({ account, chainHex }) => {
  const listeners = {};
  const provider = {
    isRabby: true,
    request: async ({ method }) => {
      switch (method) {
        case "eth_requestAccounts":
        case "eth_accounts":
          return [account];
        case "eth_chainId":
          return chainHex;
        case "net_version":
          return String(parseInt(chainHex, 16));
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
};

const browser = await chromium.launch();
const summary = [];

for (const r of routes) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1400 } });
  const errors = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text().slice(0, 200)));
  page.on("pageerror", (e) => errors.push("PAGEERROR: " + String(e).slice(0, 200)));
  await page.addInitScript(shim, { account: WHALE, chainHex: CHAIN_HEX });

  let httpStatus = "?";
  try {
    const resp = await page.goto("http://localhost:3000" + r.url, { waitUntil: "networkidle", timeout: 45000 });
    httpStatus = resp ? resp.status() : "no-resp";
  } catch (e) {
    httpStatus = "GOTO_FAIL: " + String(e).slice(0, 120);
  }
  await page.waitForTimeout(r.wait ?? 1500);

  let text = "";
  try {
    text = (await page.locator("body").innerText()).replace(/\n{2,}/g, "\n").trim();
  } catch {}

  await page.screenshot({ path: `${OUT}/${r.name}.png`, fullPage: true }).catch(() => {});
  summary.push({
    name: r.name,
    persona: r.persona,
    url: r.url,
    httpStatus,
    errors: errors.slice(0, 6),
    textLen: text.length,
    textPreview: text.slice(0, 900),
  });
  console.log(`\n=== ${r.name} (${r.persona})  ${r.url}  [${httpStatus}] ===`);
  console.log("errors:", errors.length ? errors.slice(0, 4) : "none");
  console.log("text[0..600]:\n" + text.slice(0, 600));
  await page.close();
}

fs.writeFileSync(`${OUT}/summary.json`, JSON.stringify(summary, null, 2));
console.log("\n\nDONE. screenshots + summary.json in", OUT);
await browser.close();
