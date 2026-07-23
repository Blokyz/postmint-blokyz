import type { Metadata } from "next";
import { Providers } from "@/components/Providers";
import { bodyFont, displayFont } from "@/lib/fonts";
import "./globals.css";

export const metadata: Metadata = {
  title: "Post-Mint Set Collection",
  description: "Rarity audit, set atlas, and claim races for NFT collections",
};

// Root holds wallet Providers only. Each route group supplies its own nav:
// the holder app (/, /c/[slug]/*) via HolderNav in the collection layout, and the
// operator console (/studio/*) via OperatorNav — so the two audiences never share
// a nav.
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={`${displayFont.variable} ${bodyFont.variable}`}>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
