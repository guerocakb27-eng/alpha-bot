import { useApi } from "../hooks/useApi";

const LAYERS = ["trend", "momentum", "volatility", "volume", "pattern", "sentiment"];

function cellStyle(v) {
  if (v == null) return { background: "transparent", color: "#33425e" };
  const a = Math.min(1, Math.abs(v) / 70) * 0.78 + 0.08;
  const bg = v > 0 ? `rgba(0,230,118,${a})` : v < 0 ? `rgba(255,23,68,${a})` : "rgba(106,133,168,0.12)";
  return { background: bg, color: Math.abs(v) > 35 ? "#06101c" : "#c8d8f0" };
}

const sigColor = (s) => (s === "BUY" ? "text-green" : s === "SELL" ? "text-red" : "text-yellow");

function Row({ name, symbols, lookup }) {
  return (
    <tr>
      <td className="sticky left-0 z-10 bg-panel px-3 py-1 text-text-dim whitespace-nowrap border-r border-border">{name}</td>
      {symbols.map((sym) => {
        const v = lookup(sym, name);
        return (
          <td key={sym} className="text-center px-2 py-1 font-semibold tabular-nums" style={cellStyle(v)} title={`${name} · ${sym}: ${v ?? "n/a"}`}>
            {v == null ? "·" : v > 0 ? `+${v}` : v}
          </td>
        );
      })}
    </tr>
  );
}

function SectionRow({ title, span }) {
  return (
    <tr>
      <td colSpan={span} className="sticky left-0 bg-bg px-3 py-1.5 label border-y border-border">{title}</td>
    </tr>
  );
}

export default function HeatmapTab() {
  const { data, loading, error, refresh } = useApi("/api/signals/heatmap", { pollMs: 30000 });
  const symbols = data?.symbols ?? [];
  const indicators = data?.indicators ?? [];
  const bySymbol = Object.fromEntries((data?.rows ?? []).map((r) => [r.symbol, r]));

  const layerLook = (sym, l) => bySymbol[sym]?.layers?.[l] ?? null;
  const indLook = (sym, i) => bySymbol[sym]?.indicators?.[i] ?? null;

  return (
    <div className="p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <div className="label">Indicator heatmap</div>
          <p className="text-xs text-text-dim mt-1">Latest signal per symbol — green = bullish contribution, red = bearish, by score magnitude.</p>
        </div>
        <button onClick={refresh} className="text-xs text-accent hover:underline">Refresh</button>
      </div>

      {error && <div className="panel p-4 text-sm text-red">Failed to load heatmap: {error.message}</div>}
      {loading && <div className="panel p-4 text-sm text-text-dim">Loading…</div>}
      {!loading && !error && symbols.length === 0 && (
        <div className="panel p-6 text-sm text-text-dim text-center">No signals yet — the heatmap fills in once the bot scores a cycle.</div>
      )}

      {symbols.length > 0 && (
        <div className="panel p-0 overflow-auto max-h-[75vh]">
          <table className="text-xs border-collapse w-full">
            <thead>
              <tr>
                <th className="sticky left-0 top-0 z-20 bg-panel px-3 py-2 text-left label border-r border-b border-border">Signal</th>
                {symbols.map((sym) => {
                  const r = bySymbol[sym];
                  return (
                    <th key={sym} className="sticky top-0 z-10 bg-panel px-2 py-2 border-b border-border min-w-[84px]">
                      <div className="font-extrabold tracking-wider">{sym.replace("/USDT", "")}</div>
                      <div className={`text-[10px] ${sigColor(r?.signal)}`}>{r?.signal} {r?.final_score > 0 ? "+" : ""}{r?.final_score}</div>
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              <SectionRow title="Layers" span={symbols.length + 1} />
              {LAYERS.map((l) => <Row key={l} name={l} symbols={symbols} lookup={layerLook} />)}
              <SectionRow title={`Indicators (${indicators.length})`} span={symbols.length + 1} />
              {indicators.map((i) => <Row key={i} name={i} symbols={symbols} lookup={indLook} />)}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
