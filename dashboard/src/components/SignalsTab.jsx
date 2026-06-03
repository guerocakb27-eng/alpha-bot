import { useEffect, useState } from "react";
import { useApi } from "../hooks/useApi";
import ScoreBreakdown from "./ScoreBreakdown";

function MiniBar({ value, max = 100 }) {
  const filled = Math.min(100, Math.abs(value) / max * 100);
  const color = value >= 40 ? "bg-green" : value >= 10 ? "bg-accent" : value > -10 ? "bg-yellow" : value > -40 ? "bg-red/80" : "bg-red";
  return (
    <div className="w-12 h-1 bg-bg rounded-full overflow-hidden inline-block align-middle">
      <div className={`h-full ${color}`} style={{ width: `${filled}%` }} />
    </div>
  );
}

function SignalRow({ row, selected, onClick }) {
  const score = row.final_score ?? 0;
  const sigColor = row.signal === "BUY" ? "text-green" : row.signal === "SELL" ? "text-red" : "text-yellow";
  const scoreColor = score >= 40 ? "text-green" : score >= 10 ? "text-accent" : score > -10 ? "text-yellow" : score > -40 ? "text-red/80" : "text-red";
  return (
    <tr onClick={onClick} className={`cursor-pointer transition hover:bg-bg ${selected ? "bg-bg" : ""}`}>
      <td className="py-2.5 px-3 font-extrabold tracking-wider">{row.symbol}</td>
      <td className={`py-2.5 px-3 font-extrabold ${scoreColor}`}>{score > 0 ? "+" : ""}{score}</td>
      <td className={`py-2.5 px-3 font-extrabold ${sigColor}`}>{row.signal}</td>
      <td className="py-2.5 px-3">{row.confidence}%</td>
      <td className="py-2.5 px-3 text-xs text-accent">{row.regime}</td>
      <td className="py-2.5 px-3">
        <div className="flex items-center gap-1">
          {["trend", "momentum", "volatility", "volume", "pattern", "sentiment"].map((k) => (
            <MiniBar key={k} value={row.layers?.[k] ?? 0} />
          ))}
        </div>
      </td>
    </tr>
  );
}

export default function SignalsTab({ wsEvent }) {
  const { data, loading, refresh } = useApi("/api/signals", { pollMs: 30000 });
  const [selected, setSelected] = useState(null);

  const rows = [...(data?.signals ?? [])].sort((a, b) => Math.abs(b.final_score ?? 0) - Math.abs(a.final_score ?? 0));
  const activeSymbol = selected ?? rows[0]?.symbol ?? null;

  useEffect(() => { if (wsEvent?.type === "new_signal") refresh(); }, [wsEvent]);

  return (
    <div className="grid grid-cols-1 lg:grid-cols-5 gap-4 p-4">
      <div className="lg:col-span-3 panel p-0 overflow-hidden">
        <div className="px-4 py-3 border-b border-border flex items-center justify-between">
          <div className="label">Live Signals · {rows.length} pairs</div>
          <button onClick={refresh} className="text-xs text-accent hover:underline">Refresh</button>
        </div>
        <div className="overflow-auto max-h-[70vh]">
          <table className="w-full text-sm">
            <thead className="text-[10px] text-text-dim tracking-widest uppercase border-b border-border sticky top-0 bg-panel">
              <tr>
                <th className="text-left py-2 px-3 font-semibold">Pair</th>
                <th className="text-left py-2 px-3 font-semibold">Score</th>
                <th className="text-left py-2 px-3 font-semibold">Signal</th>
                <th className="text-left py-2 px-3 font-semibold">Conf</th>
                <th className="text-left py-2 px-3 font-semibold">Regime</th>
                <th className="text-left py-2 px-3 font-semibold">T M V Vol P S</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {loading && <tr><td colSpan={6} className="px-3 py-3 text-text-dim text-xs">Loading…</td></tr>}
              {!loading && rows.length === 0 && (
                <tr><td colSpan={6} className="px-3 py-3 text-text-dim text-xs">No signals yet — the bot fills this once it scores a cycle.</td></tr>
              )}
              {rows.map((r) => (
                <SignalRow key={r.symbol} row={r} selected={activeSymbol === r.symbol} onClick={() => setSelected(r.symbol)} />
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <div className="lg:col-span-2">
        <ScoreBreakdown symbol={activeSymbol} timeframe="1h" />
      </div>
    </div>
  );
}
