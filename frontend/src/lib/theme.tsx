"use client";

// Light/dark theme state, shared app-wide. The chosen mode is persisted to
// localStorage and mirrored to <html data-theme="..."> so every scoped palette
// in globals.css (base, .race-control, .op-scope, main.studio) re-tints via
// `html[data-theme="light"]` overrides. A tiny inline script in the root layout
// applies the stored theme BEFORE hydration, so there is no dark→light flash —
// this provider only has to keep React (and RainbowKit) in sync afterwards.

import { createContext, useContext, useEffect, useState } from "react";

type Theme = "dark" | "light";

const STORAGE_KEY = "pmb:theme";

const ThemeContext = createContext<{ theme: Theme; toggle: () => void }>({
  theme: "dark",
  toggle: () => {},
});

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  // SSR renders dark (the brand default); the pre-hydration script has already
  // set the real attribute, and we sync React state to it on mount.
  const [theme, setTheme] = useState<Theme>("dark");

  useEffect(() => {
    setTheme(localStorage.getItem(STORAGE_KEY) === "light" ? "light" : "dark");
  }, []);

  const toggle = () => {
    setTheme((prev) => {
      const next: Theme = prev === "dark" ? "light" : "dark";
      window.localStorage.setItem(STORAGE_KEY, next);
      document.documentElement.dataset.theme = next;
      return next;
    });
  };

  return <ThemeContext.Provider value={{ theme, toggle }}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  return useContext(ThemeContext);
}

// Inline <script> body for the root layout: applies the stored theme before
// first paint. Kept here so the storage key lives in one place.
export const THEME_INIT_SCRIPT = `try{document.documentElement.dataset.theme=localStorage.getItem("${STORAGE_KEY}")==="light"?"light":"dark"}catch(e){document.documentElement.dataset.theme="dark"}`;
