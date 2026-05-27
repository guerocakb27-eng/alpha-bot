import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useApi } from "../hooks/useApi";
import EquityChart from "./EquityChart";
import KpiCard from "./KpiCard";

export default function PerformanceTab() {
  const { data: summary } = useApi("/api/performance", { pollMs: 30000 });
  const { data: equity } = useApi("/api/performance/equity?days=90", { pollMs: 60000 });
  const { data: regimeData } = useApi("/api/performance/by-regime", { pollMs: 60000 });

  const points = equity?.points ?? [];
  const regimeRows = regimeData?.breakdown ?? [];

  return (
    <div className="p-4 space-y-4">
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
        <KpiCard label="Win Rate" value={`${summary?.win_rate ?? 0}%`} color={summary?.win_rate >= 50 ? "text-green" : "text-yellow"} />
        <KpiCard label="Total PnL" value={`$${(summary?.total_pnl_usdt ?? 0).toFixed(2)}`}
                 color={(summary?.total_pnl_usdt ?? 0) >= 0 ? "text-green" : "text-red"} />
        <KpiCard label="Trades" value={summary?.trade_count ?? 0} />
        <KpiCard label="Profit Factor"
                 value={summary?.profit_factor === Infinity || summary?.profit_factor === null ? "∞" : (summary?.profit_factor ?? 0).toFixed(2)}
                 color={(summary?.profit_factor ?? 0) >= 1.5 ? "text-green" : "text-yellow"} />
        <KpiCard label="Avg Win / Loss"
                 value={`$${(summary?.avg_win ?? 0).toFixed(0)} / $${(summary?.avg_loss ?? 0).toFixed(0)}`} />
      </div>

      <EquityChart data={points} />

      <div className="panel p-4">
        <div className="label mb-3">Performance by Regime</div>
        {regimeRows.length === 0 ? (
          <div className="text-text-dim text-sm">No closed trades yet.</div>
        ) : (
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={regimeRows}>
                <CartesianGrid stroke="#1a2744" strokeDasharray="3 3" />
                <XAxis dataKey="regime" stroke="#4a6080" fontSize={10} />
                <YAxis stroke="#4a6080" fontSize={10} />
                <Tooltip contentStyle={{ background: "#0d1321", border: "1px solid #1a2744" }} />
                <Bar dataKey="total_pnl" fill="#00d4ff" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </div>
  );
}
