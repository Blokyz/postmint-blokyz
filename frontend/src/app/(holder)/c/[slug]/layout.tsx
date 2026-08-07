"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { HolderNav } from "@/components/HolderNav";
import { SiteHeader } from "@/components/SiteHeader";
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
    const controller = new AbortController();
    setCollection(null);
    setMissing(false);

    getCollection(slug, { signal: controller.signal })
      .then((c) => setCollection(c))
      .catch((err) => {
        if (err.name !== "AbortError") {
          setMissing(true);
        }
      });

    return () => {
      controller.abort();
    };
  }, [slug]);

  if (missing) {
    return (
      <>
        <SiteHeader />
        <div className="collection-shell">
          <p className="collection-missing">
            No contest found at <code>/c/{slug}</code>.{" "}
            <Link href="/paddock">← Back to contests</Link>
          </p>
        </div>
      </>
    );
  }

  if (!collection) {
    return (
      <>
        <SiteHeader />
        <div className="collection-shell">
          <p className="collection-loading">Loading contest…</p>
        </div>
      </>
    );
  }

  return (
    <CollectionProvider collection={collection}>
      <HolderNav />
      {children}
    </CollectionProvider>
  );
}
