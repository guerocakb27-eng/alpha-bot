import { useEffect, useRef, useState } from "react";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../hooks/useApi";
import KpiCard from "./KpiCard";

const fmt = (v, d = 2, suf = "") => (v == null ? "—" : `${v.toFixed(d)}${suf}`);
const fmtPF = (v) => (v == null ? "∞" : v.toFixed(2));   // null profit factor = no losing trades

export default function BacktestTab() {
  const [bars, setBars] = useState(400);
  const [minScore, setMinScore] = useState(10);
  const [feePct, setFeePct] = useState(0.1);
  const [slipPct, setSlipPct] = useState(0.05);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [note, setNote] = useState(null);
  const [elapsed, setElapsed] = useState(0);
  const poll = useRef(null);
  const timer = useRef(null);

  const stopTimers = () => { clearInterval(poll.current); clearInterval(timer.current); };
  useEffect(() => stopTimers, []);

  async function run() {
    stopTimers();
    setRunning(true); setError(null); setResult(null); setElapsed(0);
    try {
      const res = await api("/api/backtest", {
        method: "POST",
        body: JSON.stringify({ bars: Number(bars), min_score: Number(minScore), fee: Number(feePct) / 100, slippage: Number(slipPct) / 100 }),
      });
      setNote(res.note);
      const t0 = Date.now();
      timer.current = setInterval(() => setElapsed(Math.round((Date.now() - t0) / 1000)), 1000);
      poll.current = setInterval(async () => {
        try {
          const s = await api(`/api/backtest/${res.job_id}`);
          if (s.status === "done") { stopTimers(); setRunning(false); setResult(s.result); }
          else if (s.status === "error") { stopTimers(); setRunning(false); setError(s.error); }
        } catch (e) { stopTimers(); setRunning(false); setError(e.message); }
      }, 1500);
    } catch (e) { setRunning(false); setError(e.message); }
  }

  const m = result?.metrics;
  const equity = (result?.equity ?? []).map((p) => ({ ts: new Date(p.ts).toLocaleDateString(), equity: p.equity }));
  const fields = [["Bars", bars, setBars, 280, 800, 10], ["Min score", minScore, setMinScore, 1, 100, 1], ["Fee %", feePct, setFeePct, 0, 1, 0.01], ["Slippage %", slipPct, setSlipPct, 0, 1, 0.01]];

  return (
    <div className="p-4 space-y-4">
      <div className="panel p-4">
        <div className="label">Backtest runner</div>
        <p className="text-xs text-text-dim mt-1 mb-3">Replays the full signal bar-by-bar on the seeded synthetic dataset (offline). Runs in the background — expect ~10–40s.</p>
        <div className="flex flex-wrap items-end gap-3">
          {fields.map(([label, val, set, min, max, step]) => (
            <label key={label} className="text-xs text-text-dim flex flex-col gap-1">
              {label}
              <input type="number" value={val} min={min} max={max} step={step} onChange={(e) => set(e.target.value)}
                     className="w-24 bg-bg border border-border rounded px-2 py-1 text-text" />
            </label>
          ))}
          <button onClick={run} disabled={running}
                  className={`px-4 py-2 rounded text-sm font-semibold uppercase tracking-wider ${running ? "bg-border text-text-dim" : "bg-accent/15 text-accent hover:bg-accent/25"}`}>
            {running ? `Running… ${elapsed}s` : "Run backtest"}
          </button>
        </div>
        {note && <p className="text-[11px] text-text-dim mt-3">{note}</p>}
        {error && <p className="text-sm text-red mt-3">Backtest failed: {error}</p>}
      </div>

      {running && <div className="panel p-6 text-center text-text-dim text-sm">Crunching {bars} bars… <span className="text-accent">{elapsed}s</span></div>}

      {m && (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-6 gap-3">
            <KpiCard label="Return" value={fmt(m.total_return, 2, "%")} color={(m.total_return ?? 0) >= 0 ? "text-green" : "text-red"} />
            <KpiCard label="Sharpe" value={fmt(m.sharpe)} color={(m.sharpe ?? 0) >= 1 ? "text-green" : "text-yellow"} />
            <KpiCard label="Sortino" value={fmt(m.sortino)} />
            <KpiCard label="Win Rate" value={fmt(m.win_rate, 1, "%")} color={(m.win_rate ?? 0) >= 50 ? "text-green" : "text-yellow"} />
            <KpiCard label="Max DD" value={fmt(m.max_drawdown, 2, "%")} color="text-red" />
            <KpiCard label="Profit Factor" value={fmtPF(m.profit_factor)} color={(m.profit_factor == null || m.profit_factor >= 1.5) ? "text-green" : "text-yellow"} />
          </div>

          <div className="panel p-4 h-80">
            <div className="label mb-2">Equity curve · {m.trades} trades</div>
            <ResponsiveContainer width="100%" height="90%">
              <AreaChart data={equity}>
                <defs><linearGradient id="btEq" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#00d4ff" stopOpacity={0.4} /><stop offset="100%" stopColor="#00d4ff" stopOpacity={0} /></linearGradient></defs>
                <CartesianGrid stroke="#1a2744" strokeDasharray="3 3" />
                <XAxis dataKey="ts" stroke="#4a6080" fontSize={10} minTickGap={40} />
                <YAxis stroke="#4a6080" fontSize={10} domain={["auto", "auto"]} />
                <Tooltip contentStyle={{ background: "#0d1321", border: "1px solid #1a2744", fontFamily: "JetBrains Mono" }} />
                <Area type="monotone" dataKey="equity" stroke="#00d4ff" strokeWidth={2} fill="url(#btEq)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>

          {result.trades.length > 0 && (
            <div className="panel p-0 overflow-auto max-h-96">
              <table className="w-full text-xs">
                <thead className="text-[10px] text-text-dim uppercase tracking-widest border-b border-border sticky top-0 bg-panel">
                  <tr>
                    <th className="text-left px-3 py-2">Entry</th><th className="text-left px-3 py-2">Side</th>
                    <th className="text-right px-3 py-2">Entry px</th><th className="text-right px-3 py-2">Exit px</th>
                    <th className="text-right px-3 py-2">PnL %</th><th className="text-left px-3 py-2">Reason</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {result.trades.map((t, i) => (
                    <tr key={i}>
                      <td className="px-3 py-1.5 text-text-dim">{new Date(t.entry_time).toLocaleDateString()}</td>
                      <td className={`px-3 py-1.5 font-bold ${t.side === "BUY" ? "text-green" : "text-red"}`}>{t.side}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums">{t.entry}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums">{t.exit ?? "—"}</td>
                      <td className={`px-3 py-1.5 text-right font-bold tabular-nums ${t.pnl >= 0 ? "text-green" : "text-red"}`}>{t.pnl > 0 ? "+" : ""}{t.pnl}</td>
                      <td className="px-3 py-1.5 text-text-dim">{t.exit_reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
