// Walk the new /studio operator console against the real backend, wallet connected.
import { chromium } from "playwright";
import fs from "fs";

const OUT = "scripts/review-studio";
fs.mkdirSync(OUT, { recursive: true });

const OPERATOR = "0x70997970c51812dc3a010c7d01b50e0d17dc79c8";
const CONTRACT = "0xb8ea78fcacef50d41375e44e6814ebba36bb33c4"; // GVC — fully through pipeline
const CHAIN_HEX = "0x14a34";

const routes = [
  { name: "01-studio-home", url: "/studio", wait: 2000 },
  { name: "02-pipeline-overview", url: `/studio/${CONTRACT}`, wait: 2500 },
  { name: "03-ingest", url: `/studio/${CONTRACT}/ingest`, wait: 2500 },
  { name: "04-approve", url: `/studio/${CONTRACT}/approve`, wait: 3500 },
  { name: "05-atlas", url: `/studio/${CONTRACT}/atlas`, wait: 4000 },
  { name: "06-publish", url: `/studio/${CONTRACT}/publish`, wait: 3000 },
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
  await page.addInitScript(shim, { account: OPERATOR, chainHex: CHAIN_HEX });

  let httpStatus = "?";
  try {
    const resp = await page.goto("http://localhost:3000" + r.url, { waitUntil: "networkidle", timeout: 45000 });
    httpStatus = resp ? resp.status() : "no-resp";
  } catch (e) {
    httpStatus = "GOTO_FAIL: " + String(e).slice(0, 120);
  }
  await page.waitForTimeout(r.wait);
  let text = "";
  try {
    text = (await page.locator("body").innerText()).replace(/\n{2,}/g, "\n").trim();
  } catch {}
  await page.screenshot({ path: `${OUT}/${r.name}.png`, fullPage: true }).catch(() => {});
  summary.push({ name: r.name, url: r.url, httpStatus, errors: errors.slice(0, 6), textPreview: text.slice(0, 700) });
  console.log(`\n=== ${r.name}  ${r.url}  [${httpStatus}] ===`);
  console.log("errors:", errors.length ? errors.slice(0, 4) : "none");
  console.log(text.slice(0, 500));
  await page.close();
}
fs.writeFileSync(`${OUT}/summary.json`, JSON.stringify(summary, null, 2));
console.log("\nDONE →", OUT);
await browser.close();
