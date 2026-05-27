import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

export default function EquityChart({ data }) {
  if (!data || data.length === 0) {
    return <div className="panel p-6 text-text-dim text-sm">No closed trades yet — equity curve will appear once trades close.</div>;
  }
  const formatted = data.map((d) => ({
    ts: new Date(d.timestamp).toLocaleDateString(),
    equity: d.equity,
  }));

  return (
    <div className="panel p-4 h-80">
      <div className="label mb-2">Equity Curve</div>
      <ResponsiveContainer width="100%" height="90%">
        <AreaChart data={formatted}>
          <defs>
            <linearGradient id="equityGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#00d4ff" stopOpacity={0.4} />
              <stop offset="100%" stopColor="#00d4ff" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="#1a2744" strokeDasharray="3 3" />
          <XAxis dataKey="ts" stroke="#4a6080" fontSize={10} />
          <YAxis stroke="#4a6080" fontSize={10} domain={["auto", "auto"]} />
          <Tooltip contentStyle={{ background: "#0d1321", border: "1px solid #1a2744", fontFamily: "JetBrains Mono" }} />
          <Area type="monotone" dataKey="equity" stroke="#00d4ff" strokeWidth={2} fill="url(#equityGrad)" />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
