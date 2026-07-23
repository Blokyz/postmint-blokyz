import { connectorsForWallets } from "@rainbow-me/rainbowkit";
import {
  coinbaseWallet,
  metaMaskWallet,
  rabbyWallet,
  rainbowWallet,
  walletConnectWallet,
} from "@rainbow-me/rainbowkit/wallets";
import { createConfig, http } from "wagmi";
import { baseSepolia } from "wagmi/chains";

export const chains = [baseSepolia] as const;

const projectId = process.env.NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID || "00000000000000000000000000000000";

// Listing wallets explicitly (rather than relying on getDefaultConfig's generic
// "Injected Wallet" entry) makes RainbowKit match each option to its real
// extension via EIP-6963 rdns — so picking "MetaMask" can't resolve to whichever
// other extension last grabbed window.ethereum.
const connectors = connectorsForWallets(
  [
    {
      groupName: "Popular",
      wallets: [metaMaskWallet, rabbyWallet, coinbaseWallet, rainbowWallet, walletConnectWallet],
    },
  ],
  {
    appName: "Post-Mint Set Collection",
    projectId,
  },
);

// Optional RPC override (e.g. a local anvil node for end-to-end testing of the
// lock flow). Blank env vars come through as "" — hence || not ??.
const rpcUrl = process.env.NEXT_PUBLIC_RPC_URL || undefined;

export const wagmiConfig = createConfig({
  chains: [...chains],
  connectors,
  transports: { [baseSepolia.id]: http(rpcUrl) },
  ssr: true,
});

export const BAYC_ADDRESS = "0xBC4CA0EdA7647A8aB7C2061c2E118A18a936bC46" as const;

export const manifestRegistryAddress = process.env
  .NEXT_PUBLIC_MANIFEST_REGISTRY_ADDRESS as `0x${string}` | undefined;
