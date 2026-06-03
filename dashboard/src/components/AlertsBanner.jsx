import { AlertTriangle, X } from "lucide-react";
import { useState } from "react";
import { useApi } from "../hooks/useApi";

export default function AlertsBanner() {
  const { data } = useApi("/api/anomalies?limit=10", { pollMs: 20000 });
  const [dismissed, setDismissed] = useState(() => new Set());
  const anomalies = (data?.anomalies ?? []).filter((a) => !dismissed.has(a.id));
  if (!anomalies.length) return null;

  const top = anomalies[0];
  return (
    <div className="bg-red/10 border-b border-red/40 px-4 py-2 flex items-center gap-3 slide-in">
      <AlertTriangle className="w-4 h-4 text-red shrink-0" />
      <div className="flex-1 text-sm text-text min-w-0 truncate">
        <span className="font-semibold text-red uppercase tracking-wider text-xs mr-2">{(top.kind || "anomaly").replace(/_/g, " ")}</span>
        {top.message}
        {anomalies.length > 1 && <span className="text-text-dim text-xs ml-2">+{anomalies.length - 1} more</span>}
      </div>
      <span className="text-[10px] text-text-dim shrink-0 hidden sm:block">{top.timestamp ? new Date(top.timestamp).toLocaleString() : ""}</span>
      <button onClick={() => setDismissed((s) => new Set([...s, ...anomalies.map((a) => a.id)]))}
              className="text-text-dim hover:text-text shrink-0" title="Dismiss">
        <X className="w-4 h-4" />
      </button>
    </div>
  );
}
