/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  images: {
    // NFT images live on arbitrary metadata-declared hosts, so the optimizer
    // must accept any https origin; the gallery falls back to a plain <img>
    // for non-https sources. https-only keeps this from proxying internal
    // http endpoints.
    remotePatterns: [{ protocol: "https", hostname: "**" }],
    // NFT art is immutable — keep optimized thumbs for 30 days instead of
    // re-fetching multi-MB originals when the default TTL lapses.
    minimumCacheTTL: 2592000,
  },
};

export default nextConfig;
