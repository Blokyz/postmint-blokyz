"use client";

// Global header. The "PostMint Blocky" brand (→ home) and the theme toggle are
// ALWAYS present — the brand is the site-wide escape hatch, so no page ever
// strands the user with only the browser back button. Each section merges its
// own nav content in: `children` renders after the brand on the left,
// `actions` renders on the right before the theme toggle (e.g. ConnectButton).

import Link from "next/link";
import { ThemeToggle } from "@/components/ThemeToggle";

export function SiteHeader({
  children,
  actions,
}: {
  children?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <nav className="site-nav">
      <div className="site-nav__links">
        <Link href="/" className="site-nav__brand site-nav__home">
          PostMint&nbsp;Blocky
        </Link>
        {children}
      </div>
      <div className="site-nav__actions">
        {actions}
        <ThemeToggle />
      </div>
    </nav>
  );
}
