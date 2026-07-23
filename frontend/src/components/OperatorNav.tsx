"use client";

// Operator console nav — a pipeline stepper (Ingest → Approve → Atlas), scoped to
// one contract (`/studio/{contract}/…`). Mounted by the (operator)/studio layout.
// `contract` is undefined on the studio home (before one is chosen), where only
// the brand link shows. `Publish` lives on the Atlas page, not the stepper.

import { ConnectButton } from "@rainbow-me/rainbowkit";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { shortAddr } from "@/lib/api";

const STEPS = [
  { key: "ingest", label: "1 · Ingest" },
  { key: "approve", label: "2 · Approve" },
  { key: "atlas", label: "3 · Atlas" },
  { key: "publish", label: "4 · Publish" },
] as const;

export function OperatorNav({ contract }: { contract?: string }) {
  const pathname = usePathname();

  return (
    <nav className="site-nav">
      <div className="site-nav__links">
        <Link href="/studio" className="site-nav__brand">
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
      </div>
      <ConnectButton accountStatus="address" chainStatus="icon" showBalance={false} />
    </nav>
  );
}
