export default function KpiCard({ label, value, hint, color = "text-text" }) {
  return (
    <div className="panel p-4">
      <div className="label">{label}</div>
      <div className={`text-3xl font-extrabold mt-1 tracking-tighter ${color}`}>{value}</div>
      {hint && <div className="text-xs text-text-dim mt-1">{hint}</div>}
    </div>
  );
}
