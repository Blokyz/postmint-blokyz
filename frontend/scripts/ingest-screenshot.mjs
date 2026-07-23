import { chromium } from "playwright";

const ADDR = "0xb8ea78fcacef50d41375e44e6814ebba36bb33c4";

// Status payloads for each state we want to capture. The page never hits a real
// backend — Playwright fulfills /audit/ingest + /audit/status from these.
const STATES = {
  idle: null, // just load the page, no ingest started
  live: {
    contract_address: ADDR,
    job_id: "7f3a9c2e-41bd-4e90-bf12-9ab3c0d5e6f1",
    status: "running",
    phase: "fetching_nfts",
    progress_pct: 58,
    error_message: null,
  },
  done: {
    contract_address: ADDR,
    job_id: "7f3a9c2e-41bd-4e90-bf12-9ab3c0d5e6f1",
    status: "complete",
    phase: "done",
    progress_pct: 100,
    error_message: null,
  },
  fault: {
    contract_address: ADDR,
    job_id: "7f3a9c2e-41bd-4e90-bf12-9ab3c0d5e6f1",
    status: "failed",
    phase: "fetching_sales",
    progress_pct: 42,
    error_message: "Moralis API error: 0 NFTs returned for contract on chain eth (collection empty or unindexed).",
  },
};

const browser = await chromium.launch();
const errors = [];

for (const [name, statusBody] of Object.entries(STATES)) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } });
  page.on("console", (m) => m.type() === "error" && errors.push(`[${name}] ${m.text()}`));
  page.on("pageerror", (e) => errors.push(`[${name}] ${String(e)}`));

  await page.route("**/audit/ingest", (r) =>
    r.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ job_id: "7f3a9c2e", contract_address: ADDR, status: "pending", message: "queued" }),
    }),
  );
  if (statusBody) {
    await page.route("**/audit/status/**", (r) =>
      r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(statusBody) }),
    );
  }

  await page.goto("http://localhost:3000/ingest", { waitUntil: "networkidle" });

  if (statusBody) {
    await page.fill(".ic-input", ADDR);
    await page.click(".ic-initiate");
    await page.waitForSelector(".ic-reactor", { timeout: 15000 });
    await page.waitForTimeout(900); // let the gauge transition settle
  } else {
    await page.waitForTimeout(700); // page-load reveal
  }

  await page.screenshot({ path: `scripts/ingest-${name}.png`, fullPage: true });
  console.log(`captured: ingest-${name}.png`);
  await page.close();
}

console.log("console errors:", errors.length ? errors : "none");
await browser.close();
