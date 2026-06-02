import { useApi } from "../hooks/useApi";

const REASON_LABEL = {
  traded: "Traded",
  below_threshold: "Below threshold",
  position_exists: "Position open",
  missing_price_data: "No price data",
};

function Driver({ name, value }) {
  const color = value > 0 ? "text-green" : value < 0 ? "text-red" : "text-text-dim";
  return (
    <span className="chip bg-bg border border-border">
      <span className="text-text-dim normal-case tracking-normal">{name}</span>
      <span className={`${color} font-extrabold`}>{value > 0 ? "+" : ""}{value}</span>
    </span>
  );
}

function DecisionCard({ d }) {
  const score = d.final_score ?? 0;
  const scoreColor = score >= 40 ? "text-green" : score >= 10 ? "text-accent" : score > -10 ? "text-yellow" : score > -40 ? "text-red/80" : "text-red";
  const when = d.timestamp ? new Date(d.timestamp).toLocaleString() : "—";
  return (
    <div className="panel p-4 slide-in">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3">
          <span className="font-extrabold tracking-wider">{d.symbol}</span>
          <span className="text-xs text-text-dim">{d.timeframe}</span>
          {d.traded
            ? <span className={`chip ${d.signal === "BUY" ? "bg-green/15 text-green" : "bg-red/15 text-red"}`}>Trade {d.signal}</span>
            : <span className="chip bg-bg text-text-dim">Skip · {REASON_LABEL[d.reason] ?? d.reason}</span>}
        </div>
        <div className="flex items-center gap-4 text-xs">
          <span><span className="text-text-dim">score </span><b className={scoreColor}>{score > 0 ? "+" : ""}{score}</b></span>
          <span><span className="text-text-dim">conf </span><b>{d.confidence}%</b></span>
          <span className="text-accent">{d.regime}</span>
        </div>
      </div>

      {(d.top_layers?.length || d.top_indicators?.length) ? (
        <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <div className="label mb-1.5">Top layers</div>
            <div className="flex flex-wrap gap-1.5">
              {d.top_layers?.length ? d.top_layers.map(([n, v]) => <Driver key={n} name={n} value={v} />)
                : <span className="text-xs text-text-dim">—</span>}
            </div>
          </div>
          <div>
            <div className="label mb-1.5">Top drivers</div>
            <div className="flex flex-wrap gap-1.5">
              {d.top_indicators?.length ? d.top_indicators.map(([n, v]) => <Driver key={n} name={n} value={v} />)
                : <span className="text-xs text-text-dim">—</span>}
            </div>
          </div>
        </div>
      ) : null}

      <div className="mt-3 text-[10px] text-text-dim tracking-wider">{when}</div>
    </div>
  );
}

export default function DecisionsTab() {
  const { data, error, loading, refresh } = useApi("/api/decisions?limit=100", { pollMs: 15000 });
  const decisions = data?.decisions ?? [];

  return (
    <div className="p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <div className="label">Why did the bot do this?</div>
          <p className="text-xs text-text-dim mt-1">
            Per-signal reasoning chain. Requires <code className="text-accent">decision_logging_enabled</code> in settings.
          </p>
        </div>
        <button onClick={refresh} className="text-xs text-accent hover:underline">Refresh</button>
      </div>

      {error && <div className="panel p-4 text-sm text-red">Failed to load decisions: {error.message}</div>}
      {loading && <div className="panel p-4 text-sm text-text-dim">Loading…</div>}
      {!loading && !error && decisions.length === 0 && (
        <div className="panel p-6 text-sm text-text-dim text-center">
          No decisions logged yet. Enable <code className="text-accent">decision_logging_enabled</code> and let the bot run a cycle.
        </div>
      )}

      {decisions.map((d) => <DecisionCard key={d.id} d={d} />)}
    </div>
  );
}
