import { priorityMap, typeColorMap } from '../../engine/priorities';

export function InsightCard({ insight }) {
  const style = priorityMap[insight.priority] || priorityMap.medium;
  const typeClass = typeColorMap[insight.type] || typeColorMap['RECOMENDAÇÃO'];

  return (
    <div className={`bg-[#0d1020] border ${style.border} rounded-xl p-4 flex flex-col gap-3 transition-all hover:brightness-110`}>
      <span className={`text-[10px] font-black uppercase tracking-widest px-2 py-0.5 rounded-full w-fit ${typeClass}`}>
        {insight.type}
      </span>

      <p className="text-sm font-semibold text-white leading-snug">
        {insight.message}
      </p>

      <div className={`text-xs border-t border-white/5 pt-3 flex flex-col gap-1.5 ${style.text.replace('text-', 'text-opacity-80 text-')}`}>
        <span className="flex gap-2 text-gray-500">
          <span className="font-bold text-gray-400 min-w-[44px]">Por quê</span>
          {insight.reason}
        </span>
        <span className="flex gap-2 text-gray-500">
          <span className="font-bold text-gray-400 min-w-[44px]">Ação</span>
          {insight.action}
        </span>
      </div>

      <button
        className={`text-xs ${style.text} hover:opacity-80 text-left transition-opacity`}
        onClick={() => insight.link && (window.location.href = insight.link)}
      >
        Ver detalhes →
      </button>
    </div>
  );
}
