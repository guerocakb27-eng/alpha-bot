import { useState } from "react";
import { useApi } from "../hooks/useApi";

function fmtPct(v) { const sign = v >= 0 ? "+" : ""; return `${sign}${v?.toFixed(2) ?? "0.00"}%`; }
function fmtUsd(v) { const sign = v >= 0 ? "+" : ""; return `${sign}$${Math.abs(v ?? 0).toFixed(2)}`; }

export default function TradesTab() {
  const [filters, setFilters] = useState({ symbol: "", status: "" });
  const qs = new URLSearchParams();
  if (filters.symbol) qs.set("symbol", filters.symbol);
  if (filters.status) qs.set("status", filters.status);
  const { data, loading, error, refresh } = useApi(`/api/trades?${qs}`, { pollMs: 10000, deps: [filters.symbol, filters.status] });
  const trades = data?.trades ?? [];
  const [expanded, setExpanded] = useState(null);

  function exportCsv() {
    const headers = ["id", "symbol", "side", "entry_price", "exit_price", "qty", "pnl_usdt", "pnl_pct", "regime", "status", "entry_time", "exit_time"];
    const rows = trades.map((t) => headers.map((h) => JSON.stringify(t[h] ?? "")).join(","));
    const csv = [headers.join(","), ...rows].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `trades_${Date.now()}.csv`; a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center gap-2 flex-wrap">
        <input value={filters.symbol} onChange={(e) => setFilters({ ...filters, symbol: e.target.value })}
               placeholder="Symbol (e.g. BTC/USDT)"
               className="bg-panel border border-border rounded px-3 py-1.5 text-sm focus:border-accent outline-none" />
        <select value={filters.status} onChange={(e) => setFilters({ ...filters, status: e.target.value })}
                className="bg-panel border border-border rounded px-3 py-1.5 text-sm focus:border-accent outline-none">
          <option value="">All</option>
          <option value="OPEN">Open</option>
          <option value="CLOSED">Closed</option>
          <option value="CANCELLED">Cancelled</option>
        </select>
        <button onClick={refresh} className="text-xs text-accent hover:underline">Refresh</button>
        <button onClick={exportCsv} className="ml-auto chip bg-accent/10 text-accent border border-accent/30">Export CSV</button>
      </div>

      <div className="panel overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-[10px] text-text-dim tracking-widest uppercase border-b border-border">
            <tr>
              <th className="text-left py-2 px-3">Pair</th>
              <th className="text-left py-2 px-3">Side</th>
              <th className="text-left py-2 px-3">Entry</th>
              <th className="text-left py-2 px-3">Exit</th>
              <th className="text-left py-2 px-3">Qty</th>
              <th className="text-left py-2 px-3">PnL</th>
              <th className="text-left py-2 px-3">PnL%</th>
              <th className="text-left py-2 px-3">Score</th>
              <th className="text-left py-2 px-3">Regime</th>
              <th className="text-left py-2 px-3">Status</th>
              <th className="text-left py-2 px-3">Entered</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {loading && <tr><td colSpan={11} className="px-3 py-3 text-text-dim text-xs">Loading…</td></tr>}
            {error && <tr><td colSpan={11} className="px-3 py-3 text-red text-xs">{error.message}</td></tr>}
            {!loading && trades.length === 0 && (
              <tr><td colSpan={11} className="px-3 py-6 text-text-dim text-xs text-center">No trades yet. Open a paper position to see it here.</td></tr>
            )}
            {trades.map((t) => (
              <>
                <tr key={t.id} onClick={() => setExpanded(expanded === t.id ? null : t.id)}
                    className="cursor-pointer hover:bg-bg transition">
                  <td className="py-2 px-3 font-extrabold">{t.symbol}</td>
                  <td className={`py-2 px-3 font-extrabold ${t.side === "BUY" ? "text-green" : "text-red"}`}>{t.side}</td>
                  <td className="py-2 px-3">{t.entry_price?.toFixed(2)}</td>
                  <td className="py-2 px-3">{t.exit_price?.toFixed(2) ?? "—"}</td>
                  <td className="py-2 px-3">{t.quantity?.toFixed(6)}</td>
                  <td className={`py-2 px-3 font-extrabold ${t.pnl_usdt >= 0 ? "text-green" : "text-red"}`}>{fmtUsd(t.pnl_usdt)}</td>
                  <td className={`py-2 px-3 font-extrabold ${t.pnl_pct >= 0 ? "text-green" : "text-red"}`}>{fmtPct(t.pnl_pct)}</td>
                  <td className="py-2 px-3">{t.signal_score ?? "—"}</td>
                  <td className="py-2 px-3 text-accent text-xs">{t.market_regime ?? "—"}</td>
                  <td className="py-2 px-3 text-xs">{t.status}</td>
                  <td className="py-2 px-3 text-xs text-text-dim">{t.entry_time ? new Date(t.entry_time).toLocaleString() : "—"}</td>
                </tr>
                {expanded === t.id && (
                  <tr className="bg-bg/60">
                    <td colSpan={11} className="px-4 py-3 text-xs">
                      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                        <div><span className="label block mb-0.5">SL</span>{t.stop_loss?.toFixed(2) ?? "—"}</div>
                        <div><span className="label block mb-0.5">TP</span>{t.take_profit?.toFixed(2) ?? "—"}</div>
                        <div><span className="label block mb-0.5">Fees</span>${t.fees_usdt?.toFixed(2) ?? "0"}</div>
                        <div><span className="label block mb-0.5">Mode</span>{t.mode}</div>
                      </div>
                    </td>
                  </tr>
                )}
              </>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
