"use client";

// Operator console nav — a pipeline stepper (Ingest → Approve → Atlas), scoped to
// one contract (`/studio/{contract}/…`). Mounted by the [contract] layout and the
// studio home. `contract` is undefined on the studio home (before one is chosen),
// where only the Studio section link shows. Wraps SiteHeader, so the PostMint
// home brand + theme toggle are always present.

import { ConnectButton } from "@rainbow-me/rainbowkit";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { shortAddr } from "@/lib/api";
import { SiteHeader } from "@/components/SiteHeader";

const STEPS = [
  { key: "ingest", label: "1 · Ingest" },
  { key: "approve", label: "2 · Approve" },
  { key: "atlas", label: "3 · Atlas" },
  { key: "publish", label: "4 · Publish" },
] as const;

export function OperatorNav({ contract }: { contract?: string }) {
  const pathname = usePathname();

  return (
    <SiteHeader
      actions={<ConnectButton accountStatus="address" chainStatus="icon" showBalance={false} />}
    >
      <Link href="/studio" className="site-nav__section">
        Studio
      </Link>
      {contract &&
        STEPS.map((s) => {
          const href = `/studio/${contract}/${s.key}`;
          return (
            <Link
              key={s.key}
              href={href}
              className={pathname.startsWith(href) ? "site-nav__link is-active" : "site-nav__link"}
            >
              {s.label}
            </Link>
          );
        })}
      {contract && (
        <Link href={`/studio/${contract}`} className="site-nav__ctx">
          {shortAddr(contract)}
        </Link>
      )}
    </SiteHeader>
  );
}
