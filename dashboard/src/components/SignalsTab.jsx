import { useEffect, useState } from "react";
import { useApi } from "../hooks/useApi";
import ScoreBreakdown from "./ScoreBreakdown";

const WATCHED = ["BTC/USDT", "ETH/USDT", "SOL/USDT"];

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
    <tr onClick={onClick}
        className={`cursor-pointer transition hover:bg-bg ${selected ? "bg-bg" : ""}`}>
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
  const [selected, setSelected] = useState(null);
  const [liveRows, setLiveRows] = useState([]);
  const [loading, setLoading] = useState(true);

  async function refresh() {
    try {
      const results = await Promise.all(WATCHED.map(async (sym) => {
        const res = await fetch(`/api/indicators/${encodeURIComponent(sym)}?timeframe=1h`);
        if (!res.ok) return null;
        const j = await res.json();
        return {
          symbol: sym, final_score: j.final_score, signal: j.signal,
          confidence: j.confidence, regime: j.regime, layers: j.layers,
        };
      }));
      setLiveRows(results.filter(Boolean));
      if (!selected && results[0]) setSelected(results[0].symbol);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { refresh(); const id = setInterval(refresh, 30000); return () => clearInterval(id); }, []);

  useEffect(() => {
    if (wsEvent?.type === "new_signal") refresh();
  }, [wsEvent]);

  return (
    <div className="grid grid-cols-1 lg:grid-cols-5 gap-4 p-4">
      <div className="lg:col-span-3 panel p-0 overflow-hidden">
        <div className="px-4 py-3 border-b border-border flex items-center justify-between">
          <div className="label">Live Signals</div>
          <button onClick={refresh} className="text-xs text-accent hover:underline">Refresh</button>
        </div>
        <table className="w-full text-sm">
          <thead className="text-[10px] text-text-dim tracking-widest uppercase border-b border-border">
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
            {loading && WATCHED.map((s) => (
              <tr key={s}><td colSpan={6} className="px-3 py-3 text-text-dim text-xs">Loading {s}…</td></tr>
            ))}
            {!loading && liveRows.length === 0 && (
              <tr><td colSpan={6} className="px-3 py-3 text-text-dim text-xs">No signals available.</td></tr>
            )}
            {liveRows.map((r) => (
              <SignalRow key={r.symbol} row={r} selected={selected === r.symbol} onClick={() => setSelected(r.symbol)} />
            ))}
          </tbody>
        </table>
      </div>
      <div className="lg:col-span-2">
        <ScoreBreakdown symbol={selected} timeframe="1h" />
      </div>
    </div>
  );
}
