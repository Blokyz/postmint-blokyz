import { getDefaultConfig } from "@rainbow-me/rainbowkit";
import { baseSepolia } from "wagmi/chains";

export const chains = [baseSepolia] as const;

export const wagmiConfig = getDefaultConfig({
  appName: "Post-Mint Set Collection",
  projectId: process.env.NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID ?? "00000000000000000000000000000000",
  chains: [...chains],
  ssr: true,
});

export const BAYC_ADDRESS = "0xBC4CA0EdA7647A8aB7C2061c2E118A18a936bC46" as const;

export const manifestRegistryAddress = process.env
  .NEXT_PUBLIC_MANIFEST_REGISTRY_ADDRESS as `0x${string}` | undefined;
