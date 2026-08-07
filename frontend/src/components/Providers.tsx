"use client";

import { RainbowKitProvider, darkTheme, lightTheme } from "@rainbow-me/rainbowkit";
import "@rainbow-me/rainbowkit/styles.css";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { WagmiProvider } from "wagmi";
import { ThemeProvider, useTheme } from "@/lib/theme";
import { wagmiConfig } from "@/lib/wagmi";

const queryClient = new QueryClient();

// RainbowKit's theme is a prop, not CSS — so the wallet modal follows the app
// theme from inside ThemeProvider.
function WalletProvider({ children }: { children: React.ReactNode }) {
  const { theme } = useTheme();
  const rkTheme =
    theme === "light"
      ? lightTheme({
          accentColor: "#b8860b",
          accentColorForeground: "#fffdf6",
          borderRadius: "large",
          overlayBlur: "small",
        })
      : darkTheme({
          accentColor: "#f5c518",
          accentColorForeground: "#0e0d0b",
          borderRadius: "large",
          overlayBlur: "small",
        });
  return <RainbowKitProvider theme={rkTheme}>{children}</RainbowKitProvider>;
}

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <WagmiProvider config={wagmiConfig} reconnectOnMount>
      <QueryClientProvider client={queryClient}>
        <ThemeProvider>
          <WalletProvider>{children}</WalletProvider>
        </ThemeProvider>
      </QueryClientProvider>
    </WagmiProvider>
  );
}
