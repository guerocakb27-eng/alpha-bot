import { useApi } from "../hooks/useApi";

const LAYERS = ["trend", "momentum", "volatility", "volume", "pattern", "sentiment"];

function colorFor(score) {
  if (score >= 40) return "text-green";
  if (score >= 10) return "text-accent";
  if (score > -10) return "text-yellow";
  if (score > -40) return "text-red/80";
  return "text-red";
}
function bgFor(score) {
  if (score >= 40) return "bg-green";
  if (score >= 10) return "bg-accent";
  if (score > -10) return "bg-yellow";
  if (score > -40) return "bg-red/80";
  return "bg-red";
}

function Bar({ value }) {
  const filled = Math.min(100, Math.abs(value));
  return (
    <div className="h-1.5 bg-bg rounded-full overflow-hidden">
      <div className={`h-full ${bgFor(value)} transition-all duration-500`} style={{ width: `${filled}%` }} />
    </div>
  );
}

export default function ScoreBreakdown({ symbol, timeframe = "1h" }) {
  const path = symbol ? `/api/indicators/${encodeURIComponent(symbol)}?timeframe=${timeframe}` : null;
  const { data, loading, error } = useApi(path ?? "/health", { pollMs: 15000, deps: [symbol, timeframe] });

  if (!symbol)  return <div className="panel p-6 text-text-dim text-sm">Select a pair on the left to see its breakdown.</div>;
  if (loading)  return <div className="panel p-6 text-text-dim text-sm">Loading {symbol}…</div>;
  if (error)    return <div className="panel p-6 text-red text-sm">Failed to load: {error.message}</div>;
  if (!data?.layers) return <div className="panel p-6 text-text-dim text-sm">No data for {symbol}.</div>;

  const score = data.final_score;
  const sig = data.signal;
  const sigColor = sig === "BUY" ? "text-green border-green/40 bg-green/10"
                  : sig === "SELL" ? "text-red border-red/40 bg-red/10"
                  : "text-yellow border-yellow/40 bg-yellow/10";

  const indicators = Object.entries(data.indicators || {});
  const bullish = indicators.filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]).slice(0, 3);
  const bearish = indicators.filter(([, v]) => v < 0).sort((a, b) => a[1] - b[1]).slice(0, 3);

  return (
    <div className="panel p-6 space-y-5 slide-in">
      <div className="flex items-center justify-between">
        <div>
          <div className="label">Pair</div>
          <div className="text-lg font-extrabold tracking-wider">{symbol}</div>
        </div>
        <span className={`chip ${sigColor} text-base px-3 py-1.5 font-extrabold tracking-widest`}>{sig}</span>
      </div>

      <div className="flex items-end gap-4">
        <div>
          <div className="label">Final Score</div>
          <div className={`text-6xl font-extrabold leading-none ${colorFor(score)} tracking-tighter`}>
            {score > 0 ? "+" : ""}{score}
          </div>
        </div>
        <div className="pb-1 space-y-0.5">
          <div className="text-xs text-text-dim">Confidence <span className="text-text font-extrabold ml-1">{data.confidence}%</span></div>
          <div className="text-xs text-text-dim">Regime <span className="text-accent ml-1">{data.regime}</span></div>
        </div>
      </div>

      <div className="space-y-2.5">
        <div className="label">Layer Breakdown</div>
        {LAYERS.map((layer) => {
          const v = data.layers[layer] ?? 0;
          return (
            <div key={layer} className="space-y-1">
              <div className="flex justify-between text-xs">
                <span className="capitalize text-text-dim">{layer}</span>
                <span className={`font-extrabold ${colorFor(v)}`}>{v > 0 ? "+" : ""}{v}</span>
              </div>
              <Bar value={v} />
            </div>
          );
        })}
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <div className="label text-green mb-1">Top Bullish</div>
          {bullish.length === 0 && <div className="text-xs text-text-dim">—</div>}
          {bullish.map(([k, v]) => (
            <div key={k} className="flex justify-between text-xs py-0.5">
              <span className="text-text-dim">{k}</span>
              <span className="text-green font-extrabold">+{v}</span>
            </div>
          ))}
        </div>
        <div>
          <div className="label text-red mb-1">Top Bearish</div>
          {bearish.length === 0 && <div className="text-xs text-text-dim">—</div>}
          {bearish.map(([k, v]) => (
            <div key={k} className="flex justify-between text-xs py-0.5">
              <span className="text-text-dim">{k}</span>
              <span className="text-red font-extrabold">{v}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="text-[10px] text-text-dim border-t border-border pt-2">
        Last update: {new Date(data.timestamp).toLocaleTimeString()}
      </div>
    </div>
  );
}
