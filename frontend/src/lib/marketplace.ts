/**
 * Marketplace deep-link URL utilities (OpenSea).
 *
 * Constructs chain-aware, trait-filtered URLs sorted price-low-first so
 * holders can easily purchase qualifying tokens for short set tiers.
 */

function normalizeChainName(chain: string): string {
  const lc = chain.toLowerCase();
  return lc === "eth" ? "ethereum" : lc === "polygon" ? "matic" : lc;
}

/**
 * OpenSea trait-filtered listing URL sorted price low-to-high.
 */
export function buildOpenSeaTraitUrl(
  chain: string,
  contractAddress: string,
  category: string,
  value: string
): string {
  const chainName = normalizeChainName(chain);
  const c = encodeURIComponent(category);
  const v = encodeURIComponent(value);
  return `https://opensea.io/assets/${chainName}/${contractAddress.toLowerCase()}?search[stringTraits][0][name]=${c}&search[stringTraits][0][values][0]=${v}&sortBy=PRICE_LOWEST`;
}

/**
 * Direct OpenSea NFT token URL.
 */
export function buildOpenSeaTokenUrl(
  chain: string,
  contractAddress: string,
  tokenId: number
): string {
  const chainName = normalizeChainName(chain);
  return `https://opensea.io/assets/${chainName}/${contractAddress.toLowerCase()}/${tokenId}`;
}
