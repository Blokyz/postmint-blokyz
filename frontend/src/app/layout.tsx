import type { Metadata } from "next";
import { GlowCards } from "@/components/GlowCards";
import { Providers } from "@/components/Providers";
import { SiteFooter } from "@/components/SiteFooter";
import { bodyFont, displayFont } from "@/lib/fonts";
import { THEME_INIT_SCRIPT } from "@/lib/theme";
import "./globals.css";

export const metadata: Metadata = {
  title: "Post-Mint Set Collection",
  description: "Rarity audit, set atlas, and claim races for NFT collections",
};

// Root holds wallet Providers only. Every page renders a SiteHeader-based nav
// (the PostMint home brand + theme toggle are always present): the holder app
// via HolderNav / the pages' own SiteHeader, the operator console via
// OperatorNav. The inline script applies the stored light/dark theme before
// first paint (no flash).
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className={`${displayFont.variable} ${bodyFont.variable}`}>
        <Providers>
          {children}
          <SiteFooter />
          <GlowCards />
        </Providers>
      </body>
    </html>
  );
}
