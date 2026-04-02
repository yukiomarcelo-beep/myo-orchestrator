export function HealthScore({ score }) {
  const color =
    score > 70 ? 'text-green-400' :
    score > 40 ? 'text-yellow-400' :
    'text-red-400';

  const ringColor =
    score > 70 ? 'stroke-green-400' :
    score > 40 ? 'stroke-yellow-400' :
    'stroke-red-400';

  const label =
    score > 70 ? 'Saudável' :
    score > 40 ? 'Atenção' :
    'Crítico';

  const circumference = 2 * Math.PI * 36;
  const dash = (score / 100) * circumference;

  return (
    <div className="bg-[#111633] border border-[#1f2a44] rounded-xl p-4 flex items-center gap-4">
      <div className="relative w-20 h-20 flex-shrink-0">
        <svg viewBox="0 0 80 80" className="w-20 h-20 -rotate-90">
          <circle cx="40" cy="40" r="36" fill="none" stroke="#1f2a44" strokeWidth="6" />
          <circle
            cx="40" cy="40" r="36" fill="none"
            className={ringColor}
            strokeWidth="6"
            strokeDasharray={`${dash} ${circumference}`}
            strokeLinecap="round"
            style={{ transition: 'stroke-dasharray 1s ease' }}
          />
        </svg>
        <span className={`absolute inset-0 flex items-center justify-center text-lg font-bold ${color}`}>
          {score}
        </span>
      </div>

      <div>
        <p className="text-xs text-gray-500 uppercase tracking-widest mb-0.5">Health Score</p>
        <p className={`text-2xl font-bold ${color}`}>{label}</p>
        <p className="text-xs text-gray-600 mt-1">
          {score > 70 ? 'Sistema operando com excelência' :
           score > 40 ? 'Alguns indicadores merecem atenção' :
           'Ação imediata necessária'}
        </p>
      </div>
    </div>
  );
}
