import { useEffect, useState } from "react";
import { api, useApi } from "../hooks/useApi";

function SliderRow({ label, value, min, max, step = 1, suffix = "", onChange }) {
  return (
    <div className="space-y-1.5">
      <div className="flex justify-between text-xs">
        <span className="text-text-dim">{label}</span>
        <span className="text-accent font-extrabold">{value}{suffix}</span>
      </div>
      <input type="range" min={min} max={max} step={step} value={value}
             onChange={(e) => onChange(Number(e.target.value))}
             className="w-full accent-accent" />
    </div>
  );
}

function Toggle({ label, value, onChange }) {
  return (
    <label className="flex items-center justify-between cursor-pointer">
      <span className="text-xs text-text-dim">{label}</span>
      <button onClick={() => onChange(!value)}
              className={`w-10 h-5 rounded-full transition relative ${value ? "bg-accent" : "bg-border"}`}>
        <span className={`absolute top-0.5 ${value ? "left-5" : "left-0.5"} transition w-4 h-4 rounded-full bg-bg`} />
      </button>
    </label>
  );
}

export default function SettingsTab() {
  const { data: settings, refresh } = useApi("/api/settings");
  const { data: weights } = useApi("/api/weights");
  const [local, setLocal] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (settings && !local) setLocal({ ...settings });
  }, [settings]);

  if (!local) return <div className="p-4 text-text-dim">Loading settings…</div>;

  function set(k, v) { setLocal({ ...local, [k]: v }); }

  async function save() {
    setSaving(true);
    try {
      const diff = {};
      for (const k of Object.keys(local)) {
        if (JSON.stringify(local[k]) !== JSON.stringify(settings[k])) diff[k] = local[k];
      }
      if (Object.keys(diff).length === 0) { alert("No changes"); return; }
      await api("/api/settings", { method: "POST", body: JSON.stringify({ updates: diff, updated_by: "dashboard" }) });
      await refresh();
      alert("Saved.");
    } catch (e) {
      alert("Save failed: " + e.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="p-4 grid grid-cols-1 lg:grid-cols-2 gap-4">
      <div className="panel p-5 space-y-4">
        <div className="label">Risk Management</div>
        <SliderRow label="Risk per Trade" value={local.risk_per_trade_pct ?? 1} min={0.1} max={5} step={0.1} suffix="%"
                   onChange={(v) => set("risk_per_trade_pct", v)} />
        <SliderRow label="Min Signal Score" value={local.min_signal_score ?? 65} min={50} max={90}
                   onChange={(v) => set("min_signal_score", v)} />
        <SliderRow label="Min Confidence" value={local.min_confidence ?? 60} min={30} max={95} suffix="%"
                   onChange={(v) => set("min_confidence", v)} />
        <SliderRow label="Max Open Positions" value={local.max_open_positions ?? 3} min={1} max={10}
                   onChange={(v) => set("max_open_positions", v)} />
        <SliderRow label="SL ATR Multiplier" value={local.sl_atr_multiplier ?? 1.5} min={0.5} max={4} step={0.1}
                   onChange={(v) => set("sl_atr_multiplier", v)} />
        <SliderRow label="RR Ratio" value={local.rr_ratio ?? 2} min={1} max={5} step={0.1}
                   onChange={(v) => set("rr_ratio", v)} />
        <SliderRow label="Max Daily Loss" value={local.max_daily_loss_pct ?? 5} min={1} max={15} step={0.5} suffix="%"
                   onChange={(v) => set("max_daily_loss_pct", v)} />
      </div>

      <div className="panel p-5 space-y-4">
        <div className="label">Bot Configuration</div>
        <Toggle label="Sentiment Engine" value={!!local.sentiment_engine} onChange={(v) => set("sentiment_engine", v)} />
        <Toggle label="Self-Learning" value={!!local.self_learning} onChange={(v) => set("self_learning", v)} />
        <Toggle label="Trailing Stop" value={!!local.trailing_stop} onChange={(v) => set("trailing_stop", v)} />

        <div>
          <div className="label mb-2">Watched Pairs</div>
          <div className="flex flex-wrap gap-1.5">
            {(local.watched_pairs ?? []).map((p) => (
              <span key={p} className="chip bg-accent/10 text-accent border border-accent/30">
                {p}
                <button onClick={() => set("watched_pairs", local.watched_pairs.filter((x) => x !== p))}
                        className="hover:text-red ml-1">×</button>
              </span>
            ))}
            <input placeholder="Add pair…"
                   onKeyDown={(e) => { if (e.key === "Enter" && e.target.value) { set("watched_pairs", [...(local.watched_pairs ?? []), e.target.value.toUpperCase()]); e.target.value = ""; } }}
                   className="bg-panel border border-border rounded px-2 py-1 text-xs focus:border-accent outline-none w-28" />
          </div>
        </div>

        <div>
          <div className="label mb-2">Timeframes</div>
          <div className="flex flex-wrap gap-1">
            {["1m", "5m", "15m", "1h", "4h", "1d"].map((tf) => {
              const active = (local.timeframes ?? []).includes(tf);
              return (
                <button key={tf} onClick={() => set("timeframes", active ? local.timeframes.filter((x) => x !== tf) : [...(local.timeframes ?? []), tf])}
                        className={`chip ${active ? "bg-accent/15 text-accent border border-accent/40" : "bg-panel border border-border text-text-dim"}`}>
                  {tf}
                </button>
              );
            })}
          </div>
        </div>
      </div>

      <div className="panel p-5 lg:col-span-2">
        <div className="label mb-3">Current Indicator Weights (per regime)</div>
        {!weights ? <div className="text-text-dim text-sm">Loading…</div> : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-[10px] text-text-dim uppercase tracking-wider">
                <tr>
                  <th className="text-left py-1 px-2">Regime</th>
                  <th className="text-right py-1 px-2">Trend</th>
                  <th className="text-right py-1 px-2">Momentum</th>
                  <th className="text-right py-1 px-2">Volatility</th>
                  <th className="text-right py-1 px-2">Volume</th>
                  <th className="text-right py-1 px-2">Pattern</th>
                  <th className="text-right py-1 px-2">Sentiment</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {Object.entries(weights).map(([regime, w]) => (
                  <tr key={regime}>
                    <td className="py-1.5 px-2 text-accent">{regime}</td>
                    <td className="py-1.5 px-2 text-right">{(w.trend * 100).toFixed(0)}%</td>
                    <td className="py-1.5 px-2 text-right">{(w.momentum * 100).toFixed(0)}%</td>
                    <td className="py-1.5 px-2 text-right">{(w.volatility * 100).toFixed(0)}%</td>
                    <td className="py-1.5 px-2 text-right">{(w.volume * 100).toFixed(0)}%</td>
                    <td className="py-1.5 px-2 text-right">{(w.pattern * 100).toFixed(0)}%</td>
                    <td className="py-1.5 px-2 text-right">{(w.sentiment * 100).toFixed(0)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="lg:col-span-2 flex items-center justify-end gap-2">
        <button onClick={() => setLocal({ ...settings })} className="chip bg-panel border border-border text-text-dim">Discard</button>
        <button onClick={save} disabled={saving}
                className="chip bg-accent text-bg font-extrabold disabled:opacity-50">
          {saving ? "Saving…" : "Save Changes"}
        </button>
      </div>
    </div>
  );
}
