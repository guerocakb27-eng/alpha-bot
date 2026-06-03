import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useState } from "react";
import { useApi } from "../hooks/useApi";

const LAYERS = ["trend", "momentum", "volatility", "volume", "pattern", "sentiment"];
const LAYER_COLOR = {
  trend: "#00d4ff", momentum: "#00e676", volatility: "#ffea00",
  volume: "#a855f7", pattern: "#ff8c00", sentiment: "#ff1744",
};
const REGIMES = ["TRENDING_BULL", "TRENDING_BEAR", "RANGING", "HIGH_VOLATILITY", "SQUEEZE"];
const AXIS = "#4a6080";
const TOOLTIP = { background: "#0d1321", border: "1px solid #1a2744", fontFamily: "JetBrains Mono", fontSize: 12 };

const pct = (v) => `${Math.round(v * 100)}%`;

function Legend() {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1.5 mt-3">
      {LAYERS.map((l) => (
        <span key={l} className="flex items-center gap-1.5 text-[11px] text-text-dim">
          <span className="w-2.5 h-2.5 rounded-sm" style={{ background: LAYER_COLOR[l] }} />{l}
        </span>
      ))}
    </div>
  );
}

function WeightsByRegime() {
  const { data, loading } = useApi("/api/weights", { pollMs: 60000 });
  const rows = Object.entries(data ?? {}).map(([regime, w]) => ({ regime, ...w }));

  return (
    <div className="panel p-4">
      <div className="label">Layer weights by regime</div>
      <p className="text-xs text-text-dim mt-1 mb-3">How the signal engine splits its conviction across layers — per market regime (normalized to 100%).</p>
      {loading && <div className="text-text-dim text-sm">Loading…</div>}
      {!loading && rows.length === 0 && <div className="text-text-dim text-sm">No weight snapshots yet.</div>}
      {rows.length > 0 && (
        <>
          <div style={{ height: rows.length * 44 + 28 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={rows} layout="vertical" stackOffset="expand" margin={{ left: 8, right: 12 }}>
                <CartesianGrid stroke="#1a2744" strokeDasharray="3 3" horizontal={false} />
                <XAxis type="number" stroke={AXIS} fontSize={10} tickFormatter={pct} domain={[0, 1]} />
                <YAxis type="category" dataKey="regime" stroke={AXIS} fontSize={10} width={120} />
                <Tooltip contentStyle={TOOLTIP} formatter={(v, n) => [pct(v), n]} cursor={{ fill: "#ffffff08" }} />
                {LAYERS.map((l) => <Bar key={l} dataKey={l} stackId="w" fill={LAYER_COLOR[l]} />)}
              </BarChart>
            </ResponsiveContainer>
          </div>
          <Legend />
        </>
      )}
    </div>
  );
}

function WeightEvolution() {
  const [regime, setRegime] = useState("TRENDING_BULL");
  const { data, loading } = useApi(`/api/weights/history?regime=${regime}&limit=100`, { pollMs: 60000, deps: [regime] });
  const history = [...(data?.history ?? [])].reverse(); // API is newest-first; chart wants oldest→newest
  const points = history.map((h) => ({ ts: new Date(h.timestamp).toLocaleDateString(), ...h.weights }));
  const latest = data?.history?.[0];

  return (
    <div className="panel p-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <div className="label">Weight evolution</div>
          <p className="text-xs text-text-dim mt-1">How the learning engine has re-weighted layers over time.</p>
        </div>
        <div className="flex flex-wrap gap-1">
          {REGIMES.map((r) => (
            <button key={r} onClick={() => setRegime(r)}
                    className={`px-2 py-1 rounded text-[10px] tracking-wider font-semibold uppercase transition ${
                      regime === r ? "bg-accent/15 text-accent" : "text-text-dim hover:text-text"}`}>
              {r.replace("_", " ")}
            </button>
          ))}
        </div>
      </div>

      {latest && (
        <div className="flex items-center gap-4 text-[11px] text-text-dim mt-2">
          <span>method <b className="text-accent">{latest.optimization_method}</b></span>
          <span>samples <b className="text-text">{latest.sample_size}</b></span>
          <span>score <b className={latest.performance_score >= 0 ? "text-green" : "text-red"}>{latest.performance_score?.toFixed?.(2) ?? latest.performance_score}</b></span>
        </div>
      )}

      <div className="h-64 mt-3">
        {loading ? <div className="text-text-dim text-sm">Loading…</div>
          : points.length === 0 ? <div className="text-text-dim text-sm">No snapshots for this regime yet.</div>
          : (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={points} margin={{ left: -10, right: 12 }}>
                <CartesianGrid stroke="#1a2744" strokeDasharray="3 3" />
                <XAxis dataKey="ts" stroke={AXIS} fontSize={10} />
                <YAxis stroke={AXIS} fontSize={10} tickFormatter={pct} domain={[0, "auto"]} />
                <Tooltip contentStyle={TOOLTIP} formatter={(v, n) => [pct(v), n]} />
                {LAYERS.map((l) => <Line key={l} type="monotone" dataKey={l} stroke={LAYER_COLOR[l]} strokeWidth={2} dot={points.length < 3} />)}
              </LineChart>
            </ResponsiveContainer>
          )}
      </div>
      {points.length === 1 && (
        <p className="text-[11px] text-text-dim mt-2">Only one snapshot so far — the curve fills in as the learning engine re-weights this regime.</p>
      )}
      <Legend />
    </div>
  );
}

export default function AttributionTab() {
  return (
    <div className="p-4 space-y-4">
      <WeightsByRegime />
      <WeightEvolution />
    </div>
  );
}
