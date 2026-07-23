import { chromium } from "playwright";
const OUT = "scripts/review-studio";
const OP = "0x70997970c51812dc3a010c7d01b50e0d17dc79c8";
const WHALE = "0xf41b389e0c1950dc0b16c9498eae77131cc08a56";
const GVC = "0xb8ea78fcacef50d41375e44e6814ebba36bb33c4";
const CHAIN_HEX = "0x14a34";
const shim = ({ account, chainHex }) => {
  const provider = { isRabby: true, request: async ({ method }) => {
    if (method === "eth_requestAccounts" || method === "eth_accounts") return [account];
    if (method === "eth_chainId") return chainHex;
    if (method === "net_version") return String(parseInt(chainHex, 16));
    return null; }, on: () => provider, removeListener: () => provider };
  const detail = Object.freeze({ info: Object.freeze({ uuid: "d3adb33f-0000-4000-8000-000000000001", name: "Rabby Wallet", icon: "data:image/svg+xml;base64,PHN2Zy8+", rdns: "io.rabby" }), provider });
  const a = () => window.dispatchEvent(new CustomEvent("eip6963:announceProvider", { detail }));
  window.addEventListener("eip6963:requestProvider", a); a();
};
const browser = await chromium.launch();
async function shot(url, account, name, wait = 3500) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1500 } });
  const errs = [];
  page.on("console", (m) => m.type() === "error" && errs.push(m.text().slice(0, 140)));
  page.on("pageerror", (e) => errs.push("PAGEERR " + String(e).slice(0, 140)));
  await page.addInitScript(shim, { account, chainHex: CHAIN_HEX });
  await page.goto("http://localhost:3000" + url, { waitUntil: "networkidle", timeout: 45000 });
  await page.waitForTimeout(wait);
  await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true });
  console.log(name, "errors:", errs.length ? errs.slice(0, 3) : "none");
  await page.close();
}
await shot(`/studio/${GVC}/atlas`, OP, "10-atlas-setsize", 4500);
await shot(`/c/good-vibes-club/race`, WHALE, "11-race-real-sets", 4000);
await browser.close();
console.log("done");
