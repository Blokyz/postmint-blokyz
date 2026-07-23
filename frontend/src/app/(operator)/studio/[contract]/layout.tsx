"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { OperatorNav } from "@/components/OperatorNav";
import { ADDRESS_RE } from "@/lib/api";

// Contract-scoped operator layout. The contract is taken from the route param and
// handed to the stepper nav; every step page below reads it the same way, so no
// operator page ever asks for an address again.
export default function StudioContractLayout({ children }: { children: React.ReactNode }) {
  const params = useParams();
  const contract = String(params.contract ?? "").toLowerCase();
  const valid = ADDRESS_RE.test(contract);

  if (!valid) {
    return (
      <>
        <OperatorNav />
        <main className="studio">
          <p className="studio-error">
            <code>{contract || "—"}</code> isn&apos;t a valid contract address.{" "}
            <Link href="/studio">← Back to Studio</Link>
          </p>
        </main>
      </>
    );
  }

  return (
    <>
      <OperatorNav contract={contract} />
      {children}
    </>
  );
}
