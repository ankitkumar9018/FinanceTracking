"use client";

/* ------------------------------------------------------------------ */
/*  Mutual-fund overlap heatmap                                         */
/*  Renders a pairwise overlap matrix (weighted % of common holdings)  */
/*  as a theme-aware heatmap grid. Only funds that have constituent     */
/*  data are shown; coverage caveats are surfaced by the parent page.   */
/* ------------------------------------------------------------------ */

interface OverlapFund {
  scheme_code: string;
  scheme_name: string;
  constituents_available: boolean;
  holdings_count?: number;
}

interface OverlapCell {
  fund_a: string;
  fund_b: string;
  fund_a_code: string;
  fund_b_code: string;
  overlap_pct: number;
  common_holdings?: number;
}

interface Props {
  funds: OverlapFund[];
  matrix: OverlapCell[];
}

/* Higher overlap ⇒ more concentration risk, so tint with the loss token
   scaled by magnitude. Stays readable in both light and dark themes. */
function cellStyle(pct: number, isDiagonal: boolean): React.CSSProperties {
  if (isDiagonal) {
    return { backgroundColor: "hsl(var(--muted) / 0.6)" };
  }
  const alpha = Math.min(Math.max(pct, 0) / 100, 1) * 0.7;
  return { backgroundColor: `hsl(var(--loss) / ${alpha.toFixed(2)})` };
}

export default function MfOverlapHeatmap({ funds, matrix }: Props) {
  const covered = funds.filter((f) => f.constituents_available);

  if (covered.length < 2) {
    return (
      <p className="text-sm text-[hsl(var(--muted-foreground))]">
        At least two funds with available constituent data are required to
        display an overlap heatmap.
      </p>
    );
  }

  // Lookup keyed by an order-independent code pair.
  const lookup = new Map<string, OverlapCell>();
  for (const c of matrix) {
    lookup.set(`${c.fund_a_code}|${c.fund_b_code}`, c);
    lookup.set(`${c.fund_b_code}|${c.fund_a_code}`, c);
  }

  function valueFor(aCode: string, bCode: string): number | null {
    if (aCode === bCode) return 100;
    return lookup.get(`${aCode}|${bCode}`)?.overlap_pct ?? null;
  }

  return (
    <div className="space-y-4">
      <div className="overflow-x-auto">
        <table
          className="border-separate border-spacing-1 text-xs"
          aria-label="Pairwise mutual fund overlap heatmap"
        >
          <thead>
            <tr>
              <th className="p-1" />
              {covered.map((f, i) => (
                <th
                  key={f.scheme_code}
                  scope="col"
                  className="p-1 text-center font-medium text-[hsl(var(--muted-foreground))]"
                  title={f.scheme_name}
                >
                  F{i + 1}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {covered.map((rowF, ri) => (
              <tr key={rowF.scheme_code}>
                <th
                  scope="row"
                  className="max-w-[180px] truncate p-1 pr-2 text-right font-medium"
                  title={rowF.scheme_name}
                >
                  <span className="text-[hsl(var(--muted-foreground))]">
                    F{ri + 1}
                  </span>{" "}
                  <span className="hidden sm:inline">
                    {rowF.scheme_name.length > 22
                      ? `${rowF.scheme_name.slice(0, 22)}…`
                      : rowF.scheme_name}
                  </span>
                </th>
                {covered.map((colF, ci) => {
                  const v = valueFor(rowF.scheme_code, colF.scheme_code);
                  const isDiagonal = ri === ci;
                  return (
                    <td
                      key={colF.scheme_code}
                      className="h-10 min-w-10 rounded text-center font-mono tabular-nums"
                      style={cellStyle(v ?? 0, isDiagonal)}
                      title={`${rowF.scheme_name} × ${colF.scheme_name}: ${
                        v === null ? "n/a" : `${v.toFixed(1)}% overlap`
                      }`}
                      aria-label={`Overlap between ${rowF.scheme_name} and ${colF.scheme_name}: ${
                        v === null ? "not available" : `${v.toFixed(1)} percent`
                      }`}
                    >
                      {isDiagonal ? "—" : v === null ? "" : v.toFixed(0)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Legend: index → fund name */}
      <ul className="grid gap-1 text-xs text-[hsl(var(--muted-foreground))] sm:grid-cols-2">
        {covered.map((f, i) => (
          <li key={f.scheme_code} className="truncate" title={f.scheme_name}>
            <span className="font-medium text-[hsl(var(--foreground))]">
              F{i + 1}
            </span>{" "}
            {f.scheme_name}
          </li>
        ))}
      </ul>

      {/* Color scale hint */}
      <div className="flex items-center gap-2 text-xs text-[hsl(var(--muted-foreground))]">
        <span>Low overlap</span>
        <div className="flex h-3 flex-1 overflow-hidden rounded">
          {[0, 20, 40, 60, 80, 100].map((stop) => (
            <div
              key={stop}
              className="flex-1"
              style={cellStyle(stop, false)}
            />
          ))}
        </div>
        <span>High overlap</span>
      </div>
    </div>
  );
}
