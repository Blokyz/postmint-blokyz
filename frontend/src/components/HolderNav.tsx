"use client";

// Holder-app nav, scoped to one collection (`/c/{slug}/…`). Mounted by the
// (holder)/c/[slug] layout inside a CollectionProvider. "My Card" links to the
// connected wallet's driver card (fixes the discoverability gap). Wraps
// SiteHeader, so the PostMint home brand + theme toggle are always present;
// the collection name is the section label (→ collection landing).

import { ConnectButton } from "@rainbow-me/rainbowkit";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAccount } from "wagmi";
import { SiteHeader } from "@/components/SiteHeader";
import { useCollection } from "@/lib/collection";

export function HolderNav() {
  const { slug, display_name } = useCollection();
  const pathname = usePathname();
  const { address } = useAccount();
  const base = `/c/${slug}`;

  const links = [
    { href: `${base}/race`, label: "Race" },
    { href: `${base}/standings`, label: "Standings" },
    { href: `${base}/rules`, label: "Rules" },
  ];

  return (
    <SiteHeader
      actions={<ConnectButton accountStatus="address" chainStatus="icon" showBalance={false} />}
    >
      <Link href={base} className="site-nav__section">
        {display_name}
      </Link>
      {links.map(({ href, label }) => (
        <Link
          key={href}
          href={href}
          className={pathname.startsWith(href) ? "site-nav__link is-active" : "site-nav__link"}
        >
          {label}
        </Link>
      ))}
      {address && (
        <Link
          href={`${base}/driver/${address.toLowerCase()}`}
          className={pathname.includes("/driver/") ? "site-nav__link is-active" : "site-nav__link"}
        >
          My Card
        </Link>
      )}
    </SiteHeader>
  );
}
