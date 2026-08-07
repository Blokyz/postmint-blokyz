"use client";

// Light/dark switch — lives in every SiteHeader's action cluster, so it's on
// every page. Styled via .theme-toggle in globals.css.

import { useTheme } from "@/lib/theme";

export function ThemeToggle() {
  const { theme, toggle } = useTheme();
  const dark = theme === "dark";
  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={toggle}
      aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
      title={dark ? "Light mode" : "Dark mode"}
    >
      <span aria-hidden>{dark ? "☀" : "☾"}</span>
    </button>
  );
}
