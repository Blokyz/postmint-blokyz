"use client";

// Holder-side collection context. The `(holder)/c/[slug]/layout.tsx` resolves the
// slug → Collection once and provides it here, so every holder page reads
// `useCollection()` instead of re-fetching or passing a contract address around.

import { createContext, useContext } from "react";
import type { Collection } from "./collections";

const CollectionContext = createContext<Collection | null>(null);

export function CollectionProvider({
  collection,
  children,
}: {
  collection: Collection;
  children: React.ReactNode;
}) {
  return <CollectionContext.Provider value={collection}>{children}</CollectionContext.Provider>;
}

export function useCollection(): Collection {
  const c = useContext(CollectionContext);
  if (!c) throw new Error("useCollection must be used within a CollectionProvider");
  return c;
}
