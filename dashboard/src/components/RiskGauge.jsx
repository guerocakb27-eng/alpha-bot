import { useApi } from "../hooks/useApi";

const ACTION = {
  NORMAL:    { dot: "bg-green",  text: "text-green" },
  HALVE:     { dot: "bg-yellow", text: "text-yellow" },
  NO_NEW:    { dot: "bg-red",    text: "text-red" },
  FULL_STOP: { dot: "bg-red",    text: "text-red" },
};

// zones: left→right (best→worst), each {span, className}; marker sits at the value.
function GaugeRow({ title, value, min, max, zones }) {
  const span = max - min;
  const v = value ?? 0;
  const pos = Math.min(100, Math.max(0, ((max - v) / span) * 100));
  return (
    <div>
      <div className="flex items-center justify-between text-xs mb-1">
        <span className="text-text-dim">{title}</span>
        <span className={`font-extrabold ${v < 0 ? "text-red" : "text-green"}`}>{v > 0 ? "+" : ""}{v.toFixed(2)}%</span>
      </div>
      <div className="relative h-3 rounded-full overflow-hidden flex bg-bg">
        {zones.map((z, i) => <div key={i} className={z.className} style={{ width: `${(z.span / span) * 100}%` }} />)}
        <div className="absolute -top-0.5 -bottom-0.5 w-0.5 bg-text shadow" style={{ left: `${pos}%` }} title={`${v.toFixed(2)}%`} />
      </div>
    </div>
  );
}

export default function RiskGauge() {
  const { data, loading, error } = useApi("/api/risk", { pollMs: 30000 });

  if (error) return <div className="panel p-4 text-sm text-red">Risk unavailable: {error.message}</div>;
  if (loading || !data) return <div className="panel p-4 text-sm text-text-dim">Loading risk…</div>;

  const a = ACTION[data.action] ?? ACTION.NORMAL;
  const { day_soft, day_hard, week_hard } = data.thresholds;

  return (
    <div className="panel p-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="label">Risk posture</div>
        <span className={`chip bg-bg ${a.text}`}>
          <span className={`w-2 h-2 rounded-full ${a.dot} ${data.action !== "NORMAL" ? "pulse-dot" : ""}`} />
          {data.label}
        </span>
      </div>
      <p className="text-xs text-text-dim mt-1 mb-3">Realized day/week PnL vs. the tiered circuit breaker. Marker = current loss; bands are the size-reduce / halt tiers.</p>
      <div className="space-y-3">
        <GaugeRow title={`Day  (soft ${day_soft}% · hard ${day_hard}%)`} value={data.day_loss_pct} max={2} min={day_hard - 1}
          zones={[
            { span: 2 - day_soft, className: "bg-green/60" },
            { span: day_soft - day_hard, className: "bg-yellow/60" },
            { span: 1, className: "bg-red/60" },
          ]} />
        <GaugeRow title={`Week  (full stop ${week_hard}%)`} value={data.week_loss_pct} max={2} min={week_hard - 2}
          zones={[
            { span: 2 - week_hard, className: "bg-green/60" },
            { span: 2, className: "bg-red/60" },
          ]} />
      </div>
    </div>
  );
}
