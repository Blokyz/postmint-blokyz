"use client";

// Cursor-tracking hover glow for card surfaces (webflow "glow cards" style).
// One delegated pointermove listener writes the cursor position into --gx/--gy
// on whichever glow surface the pointer is over; the glow itself is a CSS
// ::after radial-gradient revealed on :hover (see "Glow cards" in globals.css).
// Renders nothing — mounted once in the root layout. Keep GLOW_SELECTOR in
// lockstep with the CSS rule's selector list.

import { useEffect } from "react";

const GLOW_SELECTOR = ".bento-card, .dir-card, .studio-stage, .studio-row, .atlas-tier";

export function GlowCards() {
  useEffect(() => {
    let raf = 0;
    const onMove = (e: PointerEvent) => {
      const target = e.target instanceof Element ? e.target.closest<HTMLElement>(GLOW_SELECTOR) : null;
      if (!target) return;
      if (raf) cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        const rect = target.getBoundingClientRect();
        target.style.setProperty("--gx", `${e.clientX - rect.left}px`);
        target.style.setProperty("--gy", `${e.clientY - rect.top}px`);
      });
    };
    document.addEventListener("pointermove", onMove, { passive: true });
    return () => {
      document.removeEventListener("pointermove", onMove);
      if (raf) cancelAnimationFrame(raf);
    };
  }, []);
  return null;
}
