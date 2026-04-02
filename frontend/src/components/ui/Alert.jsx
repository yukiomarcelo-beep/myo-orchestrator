const levels = {
  critical: {
    border: 'border-red-500',
    text: 'text-red-400',
    icon: '⚠',
    bg: 'bg-red-500/5'
  },
  warning: {
    border: 'border-yellow-500',
    text: 'text-yellow-400',
    icon: '⚠',
    bg: 'bg-yellow-500/5'
  },
  info: {
    border: 'border-blue-500',
    text: 'text-blue-400',
    icon: 'ℹ',
    bg: 'bg-blue-500/5'
  }
};

export function Alert({ level = 'info', title, text, reason, action, link }) {
  const s = levels[level] || levels.info;
  return (
    <div className={`border-l-4 ${s.border} ${s.bg} pl-4 pr-4 py-3 rounded-r-lg flex items-start gap-3`}>
      <span className={`${s.text} mt-0.5 flex-shrink-0`}>{s.icon}</span>
      <div className="flex-1 min-w-0">
        <p className={`text-sm font-semibold ${s.text}`}>{title || text}</p>
        {reason && (
          <p className="text-xs text-gray-500 mt-1">
            <span className="text-gray-400 font-bold">Por quê:</span> {reason}
          </p>
        )}
        {action && (
          <p className="text-xs text-gray-500 mt-0.5">
            <span className="text-gray-400 font-bold">Ação:</span> {action}
          </p>
        )}
      </div>
      {link && (
        <a href={link} className={`text-xs ${s.text} hover:opacity-80 flex-shrink-0 mt-0.5`}>
          Ver →
        </a>
      )}
    </div>
  );
}
