import { Activity, Play, Square, Repeat, AlertOctagon, Wifi, WifiOff } from "lucide-react";
import { useApi, api } from "../hooks/useApi";

function StatusChip({ ok, label }) {
  return (
    <span className={`chip ${ok ? "bg-green/10 text-green border border-green/30" : "bg-muted/10 text-muted border border-muted/30"}`}>
      <span className={`w-2 h-2 rounded-full ${ok ? "bg-green pulse-dot" : "bg-muted"}`} />
      {label}
    </span>
  );
}

export default function Header({ wsStatus }) {
  const { data, refresh } = useApi("/api/status", { pollMs: 5000 });
  const running = !!data?.running;
  const mode = data?.mode ?? "—";
  const testnet = data?.testnet;
  const openPos = data?.open_positions ?? 0;

  async function postAction(path, body) {
    try {
      await api(path, { method: "POST", body: body ? JSON.stringify(body) : "{}" });
      await refresh();
    } catch (e) {
      alert(`Action failed: ${e.message}`);
    }
  }

  return (
    <header className="border-b border-border bg-panel/60 backdrop-blur px-6 py-4">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-accent flex items-center justify-center shadow-lg shadow-accent/20">
            <Activity className="w-6 h-6 text-bg" strokeWidth={2.5} />
          </div>
          <div>
            <div className="text-xl font-extrabold tracking-wider text-text">ALPHA BOT</div>
            <div className="text-[10px] text-text-dim tracking-[0.2em] uppercase">Self-Learning Crypto Engine</div>
          </div>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <StatusChip ok={running} label={running ? "RUNNING" : "STOPPED"} />
          <span className={`chip ${mode === "PAPER" ? "bg-accent/10 text-accent border border-accent/30" : "bg-yellow/10 text-yellow border border-yellow/30"}`}>
            {mode} {testnet ? "· TESTNET" : ""}
          </span>
          <span className="chip bg-panel border border-border text-text-dim">
            POS <span className="text-text ml-1 font-extrabold">{openPos}</span>
          </span>
          <span className={`chip ${wsStatus === "open" ? "bg-green/10 text-green border border-green/30" : "bg-red/10 text-red border border-red/30"}`}>
            {wsStatus === "open" ? <Wifi className="w-3 h-3" /> : <WifiOff className="w-3 h-3" />} {wsStatus.toUpperCase()}
          </span>
        </div>

        <div className="flex items-center gap-2">
          {running ? (
            <button onClick={() => postAction("/api/bot/stop")} className="chip bg-red/15 hover:bg-red/25 text-red border border-red/40 transition">
              <Square className="w-3 h-3" /> STOP
            </button>
          ) : (
            <button onClick={() => postAction("/api/bot/start")} className="chip bg-green/15 hover:bg-green/25 text-green border border-green/40 transition">
              <Play className="w-3 h-3" /> START
            </button>
          )}
          <button onClick={() => postAction("/api/bot/mode", { mode: mode === "PAPER" ? "LIVE" : "PAPER", confirm_live: mode !== "LIVE" })}
                  className="chip bg-panel hover:bg-border text-text-dim border border-border transition">
            <Repeat className="w-3 h-3" /> TOGGLE
          </button>
          <button onClick={() => { if (confirm("Emergency stop? All positions will be queued for market close.")) postAction("/api/bot/emergency-stop"); }}
                  className="chip bg-red/15 hover:bg-red/25 text-red border border-red/40 transition">
            <AlertOctagon className="w-3 h-3" /> ESTOP
          </button>
        </div>
      </div>
    </header>
  );
}
