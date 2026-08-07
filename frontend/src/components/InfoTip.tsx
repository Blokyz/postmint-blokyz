"use client";

/**
 * Small "?" affordance with a hover/focus tooltip — the trust-and-legibility
 * explainers for race concepts (set rules, holding windows, CP, crests).
 * CSS-only reveal (`.itip` in globals.css), keyboard-reachable via tabIndex.
 */
export function InfoTip({ text }: { text: string }) {
  return (
    <span className="itip" tabIndex={0}>
      <span className="itip-q" aria-hidden>
        ?
      </span>
      <span className="itip-bubble" role="tooltip">
        {text}
      </span>
    </span>
  );
}
