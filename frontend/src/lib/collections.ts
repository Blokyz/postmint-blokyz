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
  image_url?: string;
  published?: boolean;
};

// Resolve a slug → collection. Throws ApiError(404) if the slug is free.
export const getCollection = (slug: string) => apiGet<Collection>(`/collections/${slug}`);

// Directory listing (published by default).
export const listCollections = () => apiGet<CollectionSummary[]>(`/collections`);

// Operator listing — includes unpublished/draft collections (`?all=true`).
export const listAllCollections = () => apiGet<CollectionSummary[]>(`/collections?all=true`);

// Publish / re-publish a collection under a slug.
export const publishCollection = (body: PublishRequest) => apiPost<Collection>(`/collections`, body);
