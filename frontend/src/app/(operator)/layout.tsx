// Operator route-group shell. Wraps every operator page in `.op-scope`, which
// establishes ONE utilitarian theme (dark slate + a single cyan accent) and
// overrides the holder gold-brand nav/tokens that leak in from the root layout's
// GVC reskin. Holders keep the race-control brand; operators get this console look.
export default function OperatorLayout({ children }: { children: React.ReactNode }) {
  return <div className="op-scope">{children}</div>;
}
