"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { HolderNav } from "@/components/HolderNav";
import { CollectionProvider } from "@/lib/collection";
import { Collection, getCollection } from "@/lib/collections";

// Resolves the slug → Collection once, then provides it (via CollectionProvider)
// to every holder page below + mounts the collection-scoped HolderNav. Pages read
// `useCollection()` instead of ever seeing a contract address.
export default function CollectionLayout({ children }: { children: React.ReactNode }) {
  const params = useParams();
  const slug = String(params.slug ?? "");
  const [collection, setCollection] = useState<Collection | null>(null);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    let live = true;
    getCollection(slug)
      .then((c) => live && setCollection(c))
      .catch(() => live && setMissing(true));
    return () => {
      live = false;
    };
  }, [slug]);

  if (missing) {
    return (
      <div className="collection-shell">
        <p className="collection-missing">
          No contest found at <code>/c/{slug}</code>.{" "}
          <Link href="/">← Back to contests</Link>
        </p>
      </div>
    );
  }

  if (!collection) {
    return (
      <div className="collection-shell">
        <p className="collection-loading">Loading contest…</p>
      </div>
    );
  }

  return (
    <CollectionProvider collection={collection}>
      <HolderNav />
      {children}
    </CollectionProvider>
  );
}
