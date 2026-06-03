import { BarChart3, FlaskConical, Grid3x3, HelpCircle, Layers, LineChart, ListChecks, Radio, Settings as SettingsIcon } from "lucide-react";
import { useState } from "react";
import AttributionTab from "./components/AttributionTab";
import BacktestTab from "./components/BacktestTab";
import DecisionsTab from "./components/DecisionsTab";
import HeatmapTab from "./components/HeatmapTab";
import WhatIfTab from "./components/WhatIfTab";
import Header from "./components/Header";
import PerformanceTab from "./components/PerformanceTab";
import SettingsTab from "./components/SettingsTab";
import SignalsTab from "./components/SignalsTab";
import TradesTab from "./components/TradesTab";
import { useWebSocket } from "./hooks/useWebSocket";

const TABS = [
  { id: "signals", label: "Signals", icon: Radio },
  { id: "heatmap", label: "Heatmap", icon: Grid3x3 },
  { id: "decisions", label: "Why", icon: HelpCircle },
  { id: "trades", label: "Trades", icon: ListChecks },
  { id: "performance", label: "Performance", icon: BarChart3 },
  { id: "attribution", label: "Attribution", icon: Layers },
  { id: "whatif", label: "What-If", icon: FlaskConical },
  { id: "backtest", label: "Backtest", icon: LineChart },
  { id: "settings", label: "Settings", icon: SettingsIcon },
];

export default function App() {
  const [tab, setTab] = useState("signals");
  const { status: wsStatus, lastEvent } = useWebSocket();

  return (
    <div className="min-h-screen flex flex-col">
      <Header wsStatus={wsStatus} />

      <nav className="border-b border-border bg-bg/50 px-4 flex items-center gap-1 overflow-x-auto">
        {TABS.map(({ id, label, icon: Icon }) => {
          const active = tab === id;
          return (
            <button key={id} onClick={() => setTab(id)}
                    className={`px-4 py-3 text-sm tracking-wider font-semibold uppercase border-b-2 transition flex items-center gap-2 ${
                      active ? "text-accent border-accent" : "text-text-dim border-transparent hover:text-text"
                    }`}>
              <Icon className="w-4 h-4" />
              {label}
            </button>
          );
        })}
      </nav>

      <main className="flex-1">
        {tab === "signals" && <SignalsTab wsEvent={lastEvent} />}
        {tab === "heatmap" && <HeatmapTab />}
        {tab === "decisions" && <DecisionsTab />}
        {tab === "trades" && <TradesTab />}
        {tab === "performance" && <PerformanceTab />}
        {tab === "attribution" && <AttributionTab />}
        {tab === "whatif" && <WhatIfTab />}
        {tab === "backtest" && <BacktestTab />}
        {tab === "settings" && <SettingsTab />}
      </main>

      <footer className="px-6 py-3 text-[10px] text-text-dim border-t border-border tracking-wider uppercase">
        Alpha Bot · Phase 6 dashboard · {new Date().toLocaleDateString()}
      </footer>
    </div>
  );
}
