// Prove the new-collection publish loop: name → auto-slug → availability → create
// → appears on The Paddock. Runs against the real backend, wallet connected.
import { chromium } from "playwright";

const OPERATOR = "0x70997970c51812dc3a010c7d01b50e0d17dc79c8";
const BAYC = "0xbc4ca0eda7647a8ab7c2061c2e118a18a936f13d";
const CHAIN_HEX = "0x14a34";

const shim = ({ account, chainHex }) => {
  const listeners = {};
  const provider = {
    isRabby: true,
    request: async ({ method }) => {
      if (method === "eth_requestAccounts" || method === "eth_accounts") return [account];
      if (method === "eth_chainId") return chainHex;
      if (method === "net_version") return String(parseInt(chainHex, 16));
      return null;
    },
    on: (e, f) => ((listeners[e] ??= []).push(f), provider),
    removeListener: () => provider,
  };
  const detail = Object.freeze({
    info: Object.freeze({ uuid: "d3adb33f-0000-4000-8000-000000000001", name: "Rabby Wallet", icon: "data:image/svg+xml;base64,PHN2Zy8+", rdns: "io.rabby" }),
    provider,
  });
  const a = () => window.dispatchEvent(new CustomEvent("eip6963:announceProvider", { detail }));
  window.addEventListener("eip6963:requestProvider", a);
  a();
};

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1200 } });
const errors = [];
page.on("console", (m) => m.type() === "error" && errors.push(m.text().slice(0, 160)));
page.on("pageerror", (e) => errors.push("PAGEERROR: " + String(e).slice(0, 160)));
await page.addInitScript(shim, { account: OPERATOR, chainHex: CHAIN_HEX });

await page.goto(`http://localhost:3000/studio/${BAYC}/publish`, { waitUntil: "networkidle" });
await page.waitForSelector(".pub-form", { timeout: 20000 });

await page.fill('.pub-field input[placeholder="Good Vibes Club"]', "Bored Ape Yacht Club");
// Poll availability text until it settles (max 8s).
let avail = "";
for (let i = 0; i < 40; i++) {
  await page.waitForTimeout(200);
  avail = (await page.locator(".pub-avail").innerText().catch(() => "")).trim();
  if (/Available|taken|reserved|characters|hyphens/.test(avail)) break;
}
const slug = await page.inputValue(".pub-slugwrap input");
console.log("auto-slug:", slug, "| availability:", avail);

await page.screenshot({ path: "scripts/review-studio/07-publish-new-filled.png", fullPage: true });

await page.locator(".pub-submit:not([disabled])").waitFor({ timeout: 10000 });
await page.click(".pub-submit");
await page.waitForSelector(".pub-done", { timeout: 20000 });
const done = (await page.locator(".pub-done").innerText()).replace(/\n{2,}/g, " ").trim();
console.log("published:", done.slice(0, 160));
await page.screenshot({ path: "scripts/review-studio/08-publish-done.png", fullPage: true });

// Now the holder directory should list two collections.
await page.goto("http://localhost:3000/", { waitUntil: "networkidle" });
await page.waitForTimeout(1500);
const dir = (await page.locator("body").innerText()).replace(/\n{2,}/g, "\n");
console.log("\n--- directory now shows ---\n" + dir.slice(0, 400));
await page.screenshot({ path: "scripts/review-studio/09-directory-two.png", fullPage: true });

console.log("\nconsole errors:", errors.length ? errors : "none");
await browser.close();
