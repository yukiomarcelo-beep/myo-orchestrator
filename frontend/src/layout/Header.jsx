export function Header({ lastUpdate, onReload }) {
  const time = lastUpdate
    ? lastUpdate.toLocaleTimeString('pt-BR')
    : '—';

  return (
    <div className="flex items-center justify-between mb-6">
      <div>
        <h2 className="text-xl font-bold text-white">Dashboard</h2>
        <p className="text-xs text-gray-600 mt-0.5">
          Atualizado às {time}
        </p>
      </div>
      <button
        onClick={onReload}
        className="text-xs text-gray-500 hover:text-gray-300 px-3 py-1.5 rounded-lg border border-[#1f2a44] hover:border-gray-600 transition-all"
      >
        ↻ Atualizar
      </button>
    </div>
  );
}
