"use client";

// Publish step — the only place a slug is created. Gated on a generated atlas.
// Auto-suggests a slug from the display name (mirrors backend slugify), checks
// availability live against GET /collections/{slug}, and puts the contest on the
// holder directory. Slug is immutable once set: re-publishing keeps it.

import { ConnectButton } from "@rainbow-me/rainbowkit";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { useAccount, useSignMessage } from "wagmi";
import { apiGet, ApiError, API_URL, shortAddr } from "@/lib/api";
import { buildPublishMessage, Collection, listAllCollections, publishCollection } from "@/lib/collections";

// Client mirror of backend collections_registry.slugify (preview only — the
// backend validates authoritatively).
function slugify(name: string): string {
  const ascii = name.normalize("NFKD").replace(/[^\x00-\x7F]/g, "");
  return ascii
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 40)
    .replace(/^-|-$/g, "");
}

const RESERVED = new Set([
  "c", "studio", "paddock", "api", "admin", "app", "race", "standings", "driver",
  "collections", "collection", "health", "audit", "atlas", "claim", "claims",
  "winners", "eligibility", "leaderboard", "season", "seasons", "_next",
  "static", "favicon.ico", "robots.txt", "sitemap.xml",
]);
const SLUG_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

function slugError(slug: string): string | null {
  if (slug.length < 3 || slug.length > 40) return "3–40 characters";
  if (!SLUG_RE.test(slug)) return "lowercase letters, numbers & single hyphens only";
  if (RESERVED.has(slug)) return "that word is reserved";
  return null;
}

type Avail = "idle" | "checking" | "free" | "taken" | "invalid";

export default function PublishPage() {
  const params = useParams();
  const contract = String(params.contract ?? "").toLowerCase();
  const { address, isConnected } = useAccount();
  const { signMessageAsync } = useSignMessage();

  const [gate, setGate] = useState<"loading" | "no-atlas" | "ready">("loading");
  const [existing, setExisting] = useState<Collection | null>(null);

  const [displayName, setDisplayName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugTouched, setSlugTouched] = useState(false);
  const [published, setPublished] = useState(true);

  const [avail, setAvail] = useState<Avail>("idle");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<Collection | null>(null);

  // Gate on a generated atlas, and prefill from any existing collection.
  useEffect(() => {
    let live = true;
    Promise.all([
      fetch(`${API_URL}/atlas/preview/${contract}`).then((r) => r.ok),
      listAllCollections().catch(() => []),
    ]).then(([hasAtlas, cols]) => {
      if (!live) return;
      const found = cols.find((c) => c.contract_address.toLowerCase() === contract) ?? null;
      setExisting(found);
      if (found) {
        setDisplayName(found.display_name);
        setSlug(found.slug);
        setSlugTouched(true);
        setPublished(found.published);
      }
      setGate(hasAtlas || found ? "ready" : "no-atlas");
    });
    return () => {
      live = false;
    };
  }, [contract]);

  // Auto-derive the slug from the name until the operator edits it by hand.
  useEffect(() => {
    if (!slugTouched) setSlug(slugify(displayName));
  }, [displayName, slugTouched]);

  // Live availability check (skipped for an already-registered contract — its slug
  // is fixed and legitimately "taken" by itself).
  useEffect(() => {
    if (existing) {
      setAvail("idle");
      return;
    }
    const err = slugError(slug);
    if (err) {
      setAvail(slug.length === 0 ? "idle" : "invalid");
      return;
    }
    let live = true;
    setAvail("checking");
    const t = setTimeout(() => {
      apiGet<Collection>(`/collections/${slug}`)
        .then(() => live && setAvail("taken"))
        .catch((e) => {
          if (!live) return;
          setAvail(e instanceof ApiError && e.status === 404 ? "free" : "invalid");
        });
    }, 350);
    return () => {
      live = false;
      clearTimeout(t);
    };
  }, [slug, existing]);

  const nameOk = displayName.trim().length > 0;
  const slugOk = existing !== null || avail === "free";
  const canSubmit = nameOk && slugOk && !submitting;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      const name = displayName.trim();

      // Instant slug re-verification before asking for wallet signature.
      if (!existing) {
        try {
          await apiGet<Collection>(`/collections/${slug}`);
          setAvail("taken");
          setError("That slug was taken while you were editing — please choose another.");
          setSubmitting(false);
          return;
        } catch (checkErr) {
          if (!(checkErr instanceof ApiError && checkErr.status === 404)) {
            throw checkErr;
          }
        }
      }

      // The backend uses `req.slug or ""`, so sign "" on re-publish (slug omitted).
      const signedSlug = existing ? "" : slug;

      // Operator authorization: sign the publish message when a wallet is
      // connected. Harmless in dev (allowlist off → backend ignores it); required
      // once the platform sets its operator allowlist.
      let auth: { operator_address?: string; signature?: string } = {};
      if (isConnected && address) {
        const signature = await signMessageAsync({
          message: buildPublishMessage(contract, signedSlug, name),
        });
        auth = { operator_address: address, signature };
      }

      const col = await publishCollection({
        contract_address: contract,
        display_name: name,
        // Only send slug for a first publish — re-publish keeps the existing one.
        ...(existing ? {} : { slug }),
        published,
        ...auth,
      });
      setDone(col);
      setExisting(col);
    } catch (e2) {
      if (e2 instanceof Error && /User rejected|denied|rejected the request/i.test(e2.message)) {
        setError("Signature rejected in your wallet — publishing needs your signature.");
      } else {
        setError(e2 instanceof ApiError ? e2.message : e2 instanceof Error ? e2.message : "Publish failed");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="studio studio-publish">
      <header className="studio-top">
        <div>
          <span className="studio-kicker">Publish · {shortAddr(contract)}</span>
          <h1 className="studio-h1">Publish contest</h1>
        </div>
      </header>

      {gate === "loading" && <p className="studio-note">Checking pipeline…</p>}

      {gate === "no-atlas" && (
        <section className="pub-gate">
          <p className="studio-note">
            You need a generated Set Atlas before publishing — that&apos;s what defines the tiers holders
            race for.
          </p>
          <Link href={`/studio/${contract}/atlas`} className="studio-stage-btn">
            ← Go to Set Atlas
          </Link>
        </section>
      )}

      {gate === "ready" && (
        <form onSubmit={submit} className="pub-form">
          <label className="pub-field">
            <span className="pub-label">Display name</span>
            <input
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="Good Vibes Club"
              maxLength={80}
            />
          </label>

          <label className="pub-field">
            <span className="pub-label">
              Slug {existing && <span className="pub-fixed">· fixed once published</span>}
            </span>
            <div className="pub-slugwrap">
              <span className="pub-slugprefix">/c/</span>
              <input
                type="text"
                value={slug}
                disabled={existing !== null}
                onChange={(e) => {
                  setSlugTouched(true);
                  setSlug(e.target.value.toLowerCase());
                }}
                placeholder="good-vibes-club"
              />
            </div>
            {!existing && (
              <span className={`pub-avail is-${avail}`}>
                {avail === "checking" && "Checking availability…"}
                {avail === "free" && "✓ Available"}
                {avail === "taken" && "✗ Already taken"}
                {avail === "invalid" && `✗ ${slugError(slug) ?? "invalid slug"}`}
                {avail === "idle" && "Auto-suggested from the name — edit to customise."}
              </span>
            )}
          </label>

          <label className="pub-toggle">
            <input type="checkbox" checked={published} onChange={(e) => setPublished(e.target.checked)} />
            <span>Visible on The Paddock (holder directory)</span>
          </label>

          {!isConnected && (
            <div className="pub-connect">
              <span className="pub-fixed">Connect your operator wallet to sign the publish.</span>
              <ConnectButton accountStatus="address" chainStatus="none" showBalance={false} />
            </div>
          )}

          <button type="submit" className="pub-submit" disabled={!canSubmit}>
            {submitting
              ? isConnected
                ? "Signing & publishing…"
                : "Publishing…"
              : existing
                ? "Update contest"
                : "Publish contest"}
          </button>
          {error && <p className="studio-error">{error}</p>}
        </form>
      )}

      {done && (
        <section className="pub-done">
          <div className="studio-section-label">// live</div>
          <p>
            <strong>{done.display_name}</strong> is {done.published ? "live" : "saved as a draft"} at{" "}
            <code>/c/{done.slug}</code>.
          </p>
          <div className="pub-done-links">
            <Link href={`/c/${done.slug}`} className="studio-stage-btn">
              View holder page ▸
            </Link>
            <Link href="/paddock" className="studio-stage-btn is-ghost">
              The Paddock
            </Link>
          </div>
        </section>
      )}
    </main>
  );
}
