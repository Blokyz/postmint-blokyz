// Typed client for the collections registry (backend app/api/collections.py).
// Powers slug resolution (holder layout), the collections directory, and the
// operator Publish step.

import { apiGet, apiPost } from "./api";

export type Collection = {
  slug: string;
  contract_address: `0x${string}`;
  display_name: string;
  chain: string;
  image_url: string | null;
  published: boolean;
};

export type CollectionSummary = Collection & {
  tier_count: number;
  total_cap: number;
  total_filled: number;
  racers: number;
  status: "live" | "ending_soon" | "full" | "pending";
};

export type PublishRequest = {
  contract_address: string;
  display_name: string;
  slug?: string;
  published?: boolean;
  // Operator authorization (only enforced when the backend allowlist is set).
  operator_address?: string;
  signature?: string;
};

// Byte-for-byte mirror of backend app/signing.py:build_publish_message. Keep in
// lockstep — the backend recovers the signer from these exact bytes. `slug` must
// be what the request sends: the chosen slug on first publish, "" on re-publish
// (the backend uses `req.slug or ""`).
export function buildPublishMessage(contract: string, slug: string, displayName: string): string {
  return `PostMint collection publish\ncontract:${contract.toLowerCase()}\nslug:${slug}\nname:${displayName}`;
}

// Resolve a slug → collection. Throws ApiError(404) if the slug is free.
export const getCollection = (slug: string, options?: RequestInit) => apiGet<Collection>(`/collections/${slug}`, options);

// Directory listing (published by default).
export const listCollections = () => apiGet<CollectionSummary[]>(`/collections`);

// Operator listing — includes unpublished/draft collections (`?all=true`).
export const listAllCollections = () => apiGet<CollectionSummary[]>(`/collections?all=true`);

// Publish / re-publish a collection under a slug.
export const publishCollection = (body: PublishRequest) => apiPost<Collection>(`/collections`, body);
