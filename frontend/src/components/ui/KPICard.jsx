export function KPICard({ title, value, delta, insight, colorClass, deltaLabel }) {
  const deltaDir = delta > 0 ? 'up' : delta < 0 ? 'down' : 'flat';
  const deltaColor = deltaDir === 'up' ? 'text-green-400' : deltaDir === 'down' ? 'text-red-400' : 'text-gray-500';
  const arrow = deltaDir === 'up' ? '↑' : deltaDir === 'down' ? '↓' : '→';

  return (
    <div className="bg-[#111633] border border-[#1f2a44] rounded-xl p-4 flex flex-col gap-1 transition-all hover:-translate-y-0.5 hover:shadow-lg">
      <p className="text-[10px] font-bold uppercase tracking-widest text-gray-500">{title}</p>
      <p className={`text-2xl font-bold ${colorClass}`}>{value}</p>
      {delta !== undefined && (
        <p className={`text-xs ${deltaColor}`}>
          {arrow} {Math.abs(delta)}% {deltaLabel}
        </p>
      )}
      {insight && (
        <p className="text-[10px] text-gray-600 border-t border-white/5 pt-1.5 mt-0.5 leading-relaxed">
          {insight}
        </p>
      )}
    </div>
  );
}
