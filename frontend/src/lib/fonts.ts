// Shared holder-app fonts. GVC-style: a chunky, rounded, friendly display face
// (Fredoka) + a warm rounded body sans (Nunito). We keep the original CSS variable
// names (--font-race-display / --font-race-mono) so every existing rule + page
// className flows through unchanged — only the actual typefaces change.

import { Fredoka, Nunito } from "next/font/google";

export const displayFont = Fredoka({
  subsets: ["latin"],
  weight: ["500", "600", "700"],
  variable: "--font-race-display",
});

export const bodyFont = Nunito({
  subsets: ["latin"],
  weight: ["400", "600", "700", "800"],
  variable: "--font-race-mono",
});
