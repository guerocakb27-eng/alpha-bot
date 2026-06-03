import { useEffect, useState } from "react";
import { api, useApi } from "../hooks/useApi";

const LAYERS = ["trend", "momentum", "volume", "volatility", "pattern", "sentiment"];
const sigColor = (s) => (s === "BUY" ? "text-green" : s === "SELL" ? "text-red" : "text-yellow");
const scoreColor = (v) => (v >= 40 ? "text-green" : v >= 10 ? "text-accent" : v > -10 ? "text-yellow" : v > -40 ? "text-red/80" : "text-red");

export default function WhatIfTab() {
  const { data: sigData } = useApi("/api/signals");
  const { data: weightsData } = useApi("/api/weights");
  const { data: settingsData } = useApi("/api/settings");

  const signals = sigData?.signals ?? [];
  const [symbol, setSymbol] = useState(null);
  const [layerScores, setLayerScores] = useState(null);
  const [weights, setWeights] = useState(null);
  const [mode, setMode] = useState("weighted");
  const [minScore, setMinScore] = useState(65);
  const [result, setResult] = useState(null);

  const selected = signals.find((s) => s.symbol === symbol) ?? signals[0];

  useEffect(() => {
    if (settingsData?.min_signal_score != null) setMinScore(settingsData.min_signal_score);
  }, [settingsData]);

  // seed sliders from the selected signal + that regime's weights (on load / symbol change)
  useEffect(() => {
    if (!selected) return;
    if (!symbol) setSymbol(selected.symbol);
    setLayerScores({ ...selected.layers });
    const rw = weightsData?.[selected.regime];
    setWeights(rw ? { ...rw } : Object.fromEntries(LAYERS.map((l) => [l, +(1 / LAYERS.length).toFixed(2)])));
  }, [symbol, sigData, weightsData]);

  // debounced re-score via the shared backend scorer (parity with the live path)
  useEffect(() => {
    if (!layerScores || !weights) return;
    const id = setTimeout(async () => {
      try {
        setResult(await api("/api/whatif", {
          method: "POST",
          body: JSON.stringify({ layer_scores: layerScores, weights, mode, min_score: Number(minScore) }),
        }));
      } catch { /* ignore transient */ }
    }, 200);
    return () => clearTimeout(id);
  }, [layerScores, weights, mode, minScore]);

  if (!signals.length) return <div className="p-4"><div className="panel p-6 text-text-dim text-sm text-center">No signals yet — the what-if simulator needs a scored signal to seed from.</div></div>;
  if (!layerScores || !weights) return <div className="p-4 text-text-dim text-sm">Loading…</div>;

  const weightSum = Object.values(weights).reduce((a, b) => a + Number(b), 0);
  const baseline = selected?.final_score ?? 0;
  const delta = (result?.final_score ?? 0) - baseline;

  const resetToActual = () => {
    setLayerScores({ ...selected.layers });
    const rw = weightsData?.[selected.regime];
    if (rw) setWeights({ ...rw });
    setMode("weighted");
  };

  return (
    <div className="p-4 grid grid-cols-1 lg:grid-cols-5 gap-4">
      <div className="lg:col-span-3 panel p-4 space-y-4">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div className="label">What-if simulator</div>
          <div className="flex items-center gap-1">
            {signals.map((s) => (
              <button key={s.symbol} onClick={() => setSymbol(s.symbol)}
                      className={`px-2 py-1 rounded text-[10px] font-semibold uppercase tracking-wider ${(symbol ?? selected.symbol) === s.symbol ? "bg-accent/15 text-accent" : "text-text-dim hover:text-text"}`}>
                {s.symbol.replace("/USDT", "")}
              </button>
            ))}
          </div>
        </div>
        <p className="text-xs text-text-dim">Drag layer scores and regime weights to see the resulting score. Mirrors the default scoring path (optional edge toggles excluded).</p>

        <div className="flex items-center gap-4 flex-wrap text-xs">
          <div className="flex items-center gap-1">
            {["weighted", "confluence"].map((m) => (
              <button key={m} onClick={() => setMode(m)}
                      className={`px-2 py-1 rounded uppercase tracking-wider font-semibold ${mode === m ? "bg-accent/15 text-accent" : "text-text-dim hover:text-text"}`}>{m}</button>
            ))}
          </div>
          <label className="flex items-center gap-2 text-text-dim">min score
            <input type="number" value={minScore} onChange={(e) => setMinScore(e.target.value)}
                   className="w-16 bg-bg border border-border rounded px-2 py-1 text-text" />
          </label>
          <button onClick={resetToActual} className="text-accent hover:underline ml-auto">Reset to actual</button>
        </div>

        <div>
          <div className="label mb-2">Layer scores</div>
          <div className="space-y-2">
            {LAYERS.map((l) => (
              <div key={l} className="flex items-center gap-3">
                <span className="w-20 text-xs text-text-dim">{l}</span>
                <input type="range" min={-100} max={100} value={layerScores[l] ?? 0}
                       onChange={(e) => setLayerScores({ ...layerScores, [l]: Number(e.target.value) })}
                       className="flex-1 accent-accent" />
                <span className={`w-10 text-right text-xs font-bold tabular-nums ${scoreColor(layerScores[l] ?? 0)}`}>{(layerScores[l] ?? 0) > 0 ? "+" : ""}{layerScores[l] ?? 0}</span>
              </div>
            ))}
          </div>
        </div>

        <div>
          <div className="flex items-center justify-between mb-2">
            <div className="label">Regime weights</div>
            <span className={`text-[10px] ${Math.abs(weightSum - 1) < 0.001 ? "text-text-dim" : "text-yellow"}`}>Σ {weightSum.toFixed(2)}</span>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            {LAYERS.map((l) => (
              <label key={l} className="flex items-center justify-between gap-2 bg-bg border border-border rounded px-2 py-1">
                <span className="text-xs text-text-dim">{l}</span>
                <input type="number" min={0} max={1} step={0.05} value={weights[l] ?? 0}
                       onChange={(e) => setWeights({ ...weights, [l]: Number(e.target.value) })}
                       className="w-14 bg-transparent text-right text-text text-xs" />
              </label>
            ))}
          </div>
        </div>
      </div>

      <div className="lg:col-span-2 panel p-5 flex flex-col">
        <div className="label">Projected score</div>
        <div className={`text-6xl font-extrabold mt-3 tabular-nums ${scoreColor(result?.final_score ?? 0)}`}>{(result?.final_score ?? 0) > 0 ? "+" : ""}{result?.final_score ?? "—"}</div>
        <div className={`mt-1 text-lg font-bold ${sigColor(result?.signal)}`}>{result?.signal ?? "—"}</div>

        <div className="mt-6 pt-4 border-t border-border space-y-2 text-sm">
          <div className="flex justify-between">
            <span className="text-text-dim">Actual ({selected?.symbol})</span>
            <span className={`font-bold ${scoreColor(baseline)}`}>{baseline > 0 ? "+" : ""}{baseline} · <span className={sigColor(selected?.signal)}>{selected?.signal}</span></span>
          </div>
          <div className="flex justify-between">
            <span className="text-text-dim">Δ vs actual</span>
            <span className={`font-bold ${delta > 0 ? "text-green" : delta < 0 ? "text-red" : "text-text-dim"}`}>{delta > 0 ? "+" : ""}{delta}</span>
          </div>
          <div className="flex justify-between"><span className="text-text-dim">Regime</span><span className="text-accent">{selected?.regime}</span></div>
        </div>
      </div>
    </div>
  );
}
